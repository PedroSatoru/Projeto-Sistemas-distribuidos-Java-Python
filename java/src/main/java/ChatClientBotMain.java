import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.LockSupport;
import java.util.stream.Collectors;

import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;
import org.zeromq.ZMsg;

import com.google.protobuf.InvalidProtocolBufferException;

import proto.ChatProtocol;

public class ChatClientBotMain {
    private static void log(String level, String id, String event, String message) {
        long ts = System.currentTimeMillis();
        System.out.printf(
                "[ts=%d][lang=JAVA][role=CLIENT][id=%s][lvl=%s][evt=%s] %s%n",
                ts,
                id,
                level,
                event,
                message
        );
    }

    private static void log(String level, String id, String event, String message, long messageTs) {
        System.out.printf(
                "[ts=%d][lang=JAVA][role=CLIENT][id=%s][lvl=%s][evt=%s] %s%n",
                messageTs,
                id,
                level,
                event,
                message
        );
    }

    public static void main(String[] args) throws InterruptedException {
        Config config = Config.from(args);

        try (ZContext context = new ZContext()) {
            ZMQ.Socket reqSocket = context.createSocket(SocketType.REQ);
            ZMQ.Socket subSocket = context.createSocket(SocketType.SUB);
            reqSocket.connect(config.frontendEndpoint());
            reqSocket.setReceiveTimeOut(config.timeoutMs());
            subSocket.connect(config.subEndpoint());

            log("INFO", config.username(), "CONNECT", "REQ conectado em " + config.frontendEndpoint());
            log("INFO", config.username(), "CONNECT", "SUB conectado em " + config.subEndpoint());

            if (!loginWithRetry(reqSocket, config.username(), config.loginAttempts(), config.retryDelayMs())) {
                log("ERROR", config.username(), "LOGIN_FAIL", "login falhou apos " + config.loginAttempts() + " tentativas");
                return;
            }

            Set<String> subscribedChannels = new HashSet<>();
            Thread listener = startSubscriberThread(subSocket, config.username());

            ensureAtLeastFiveChannels(reqSocket, config.username());
            ensureUpToThreeSubscriptions(reqSocket, subSocket, config.username(), subscribedChannels, config.random());
            runPublishLoop(reqSocket, subSocket, config.username(), subscribedChannels, config.random());

            listener.join();
        }
    }

    private static boolean loginWithRetry(ZMQ.Socket socket, String username, int attempts, long retryDelayMs)
            throws InterruptedException {
        for (int i = 1; i <= attempts; i++) {
            ChatProtocol.LoginRequest loginRequest = ChatProtocol.LoginRequest.newBuilder()
                    .setTimestampMs(System.currentTimeMillis())
                    .setUsername(username)
                    .build();

            ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                    .setTimestampMs(System.currentTimeMillis())
                    .setLoginRequest(loginRequest)
                    .build();

            ChatProtocol.ServerResponse response = sendAndReceive(socket, request, username, "LOGIN");
            if (response == null) {
                continue;
            }

            if (response.hasLoginResponse() && response.getLoginResponse().getSuccess()) {
                log("INFO", username, "LOGIN_OK", "login realizado com sucesso", response.getTimestampMs());
                return true;
            }

            String reason = response.hasLoginResponse()
                    ? response.getLoginResponse().getError()
                    : response.getErrorResponse().getError();

            log("WARN", username, "LOGIN_RETRY", "tentativa " + i + " falhou: " + reason, response.getTimestampMs());
            pauseMs(retryDelayMs);
        }
        return false;
    }

    private static List<String> listChannels(ZMQ.Socket socket, String username) {
        ChatProtocol.ListChannelsRequest listRequest = ChatProtocol.ListChannelsRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .build();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setListChannelsRequest(listRequest)
                .build();

        ChatProtocol.ServerResponse response = sendAndReceive(socket, request, username, "LIST_CHANNELS");
        if (response == null) {
            return List.of();
        }

        if (response.hasListChannelsResponse()) {
            List<String> channels = response.getListChannelsResponse().getChannelsList();
            log("INFO", username, "LIST_CHANNELS_OK", "canais=" + channels);
            return channels;
        }

        log("ERROR", username, "LIST_CHANNELS_FAIL", response.getErrorResponse().getError());
        return List.of();
    }

    private static boolean createChannel(ZMQ.Socket socket, String username, String channel) {
        ChatProtocol.CreateChannelRequest createRequest = ChatProtocol.CreateChannelRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setChannelName(channel)
                .build();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setCreateChannelRequest(createRequest)
                .build();

        ChatProtocol.ServerResponse response = sendAndReceive(socket, request, username, "CREATE_CHANNEL");
        if (response == null) {
            return false;
        }

        if (response.hasCreateChannelResponse() && response.getCreateChannelResponse().getSuccess()) {
            log("INFO", username, "CREATE_CHANNEL_OK", "canal criado: " + channel);
            return true;
        }

        if (response.hasCreateChannelResponse()) {
            log("WARN", username, "CREATE_CHANNEL_FAIL", "falha ao criar canal " + channel + ": " + response.getCreateChannelResponse().getError());
            return false;
        }

        log("ERROR", username, "CREATE_CHANNEL_FAIL", "erro ao criar canal " + channel + ": " + response.getErrorResponse().getError());
        return false;
    }

    private static boolean publishMessage(ZMQ.Socket socket, String username, String channel, String text) {
        ChatProtocol.PublishRequest publishRequest = ChatProtocol.PublishRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setChannelName(channel)
                .setMessageText(text)
                .setUsername(username)
                .build();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setPublishRequest(publishRequest)
                .build();

        ChatProtocol.ServerResponse response = sendAndReceive(socket, request, username, "PUBLISH");
        if (response == null) {
            return false;
        }

        if (response.hasPublishResponse() && response.getPublishResponse().getSuccess()) {
            return true;
        }

        if (response.hasPublishResponse()) {
            log("WARN", username, "PUBLISH_FAIL", response.getPublishResponse().getError(), response.getTimestampMs());
        } else {
            log("ERROR", username, "PUBLISH_FAIL", response.getErrorResponse().getError(), response.getTimestampMs());
        }
        return false;
    }

    private static Thread startSubscriberThread(ZMQ.Socket subSocket, String username) {
        Thread listener = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    ZMsg frames = ZMsg.recvMsg(subSocket, ZMQ.DONTWAIT);
                    if (frames == null) {
                        pauseMs(100);
                        continue;
                    }

                    if (frames.size() < 2) {
                        frames.destroy();
                        continue;
                    }

                    byte[] payload = frames.getLast().getData();
                    ChatProtocol.ChatMessage chatMessage = ProtocolCodec.parseChatMessage(payload);
                    long recvTs = System.currentTimeMillis();
                    frames.destroy();

                    log(
                            "INFO",
                            username,
                            "RECV_SUB",
                            "Canal: " + chatMessage.getChannelName()
                                    + " | Msg: " + chatMessage.getMessageText()
                                    + " | TS envio: " + chatMessage.getTimestampMs()
                                    + " | TS recv: " + recvTs,
                            recvTs
                    );
                } catch (InvalidProtocolBufferException ex) {
                    log("WARN", username, "SUB_PARSE_ERR", "payload protobuf invalido: " + ex.getMessage());
                } catch (RuntimeException ex) {
                    if (!Thread.currentThread().isInterrupted()) {
                        log("ERROR", username, "SUB_ERR", "erro no subscriber: " + ex.getMessage());
                    }
                }
            }
        }, "java-bot-sub-listener");

        listener.setDaemon(true);
        listener.start();
        return listener;
    }

    private static void ensureAtLeastFiveChannels(ZMQ.Socket reqSocket, String username) {
        List<String> channels = new ArrayList<>(listChannels(reqSocket, username));

        while (channels.size() < 5) {
            String channelName = "java_ch_" + UUID.randomUUID().toString().substring(0, 6);
            if (createChannel(reqSocket, username, channelName)) {
                channels = new ArrayList<>(listChannels(reqSocket, username));
            }
        }
    }

    private static void ensureUpToThreeSubscriptions(
            ZMQ.Socket reqSocket,
            ZMQ.Socket subSocket,
            String username,
            Set<String> subscribedChannels,
            Random random
    ) {
        List<String> channels = new ArrayList<>(listChannels(reqSocket, username));
        if (channels.isEmpty()) {
            return;
        }

        while (subscribedChannels.size() < 3) {
            List<String> available = channels.stream()
                    .filter(c -> !subscribedChannels.contains(c))
                    .collect(Collectors.toList());
            if (available.isEmpty()) {
                return;
            }

            String selected = available.get(random.nextInt(available.size()));
            subSocket.subscribe(selected.getBytes(StandardCharsets.UTF_8));
            subscribedChannels.add(selected);
            log("INFO", username, "SUB_OK", "inscrito em " + selected);
        }
    }

    private static void runPublishLoop(
            ZMQ.Socket reqSocket,
            ZMQ.Socket subSocket,
            String username,
            Set<String> subscribedChannels,
            Random random
    ) throws InterruptedException {
        final int maxPublishes = 10;
        int messageCounter = 0;
        while (messageCounter < maxPublishes) {
            List<String> channels = new ArrayList<>(listChannels(reqSocket, username));
            if (channels.isEmpty()) {
                pauseMs(1000);
                continue;
            }

            if (subscribedChannels.size() < 3) {
                ensureUpToThreeSubscriptions(reqSocket, subSocket, username, subscribedChannels, random);
            }

            String targetChannel = channels.get(random.nextInt(channels.size()));
            while (messageCounter < maxPublishes) {
                messageCounter++;
                String text = "Hello pub/sub " + messageCounter + " from " + username + " ["
                        + UUID.randomUUID().toString().substring(0, 4) + "]";
                publishMessage(reqSocket, username, targetChannel, text);
                pauseMs(1000);
            }
        }

        log("INFO", username, "PUBLISH_DONE", "limite de 10 publicacoes totais atingido");
    }

    private static void pauseMs(long delayMs) {
        LockSupport.parkNanos(TimeUnit.MILLISECONDS.toNanos(delayMs));
    }

    private static ChatProtocol.ServerResponse sendAndReceive(
            ZMQ.Socket socket,
            ChatProtocol.ClientRequest request,
            String username,
            String label
    ) {
        try {
            byte[] payload = ProtocolCodec.toBytes(request);
            log("INFO", username, "SEND", "action=" + label + " bytes=" + payload.length, request.getTimestampMs());
            socket.send(payload, 0);

            byte[] raw = socket.recv(0);
            if (raw == null) {
                log("ERROR", username, "TIMEOUT", "timeout na acao " + label);
                return null;
            }

            ChatProtocol.ServerResponse response = ProtocolCodec.parseServerResponse(raw);
            log("INFO", username, "RECV", "action=" + response.getActionCase() + " bytes=" + raw.length, response.getTimestampMs());
            return response;
        } catch (InvalidProtocolBufferException ex) {
            log("ERROR", username, "PROTO_INVALID", "resposta protobuf invalida em " + label + ": " + ex.getMessage());
            return null;
        } catch (RuntimeException ex) {
            log("ERROR", username, "COMM_ERROR", "erro de comunicacao em " + label + ": " + ex.getMessage());
            return null;
        }
    }

    private record Config(
            String username,
            String frontendEndpoint,
            String subEndpoint,
            int timeoutMs,
            int loginAttempts,
            long retryDelayMs,
            Random random
    ) {
        static Config from(String[] args) {
            String username = getArg(args, "--username", System.getenv().getOrDefault("BOT_USERNAME", "java_bot_1"));
            String frontend = getArg(args, "--frontend", System.getenv().getOrDefault("BROKER_FRONTEND_ENDPOINT", "tcp://broker:5555"));
            String subEndpoint = getArg(args, "--sub-endpoint", System.getenv().getOrDefault("PROXY_SUB_ENDPOINT", "tcp://python_proxy:5558"));
            int timeoutMs = Integer.parseInt(getArg(args, "--timeout-ms", System.getenv().getOrDefault("BOT_TIMEOUT_MS", "5000")));
            int loginAttempts = Integer.parseInt(getArg(args, "--login-attempts", System.getenv().getOrDefault("BOT_LOGIN_ATTEMPTS", "3")));
            long retryDelayMs = Long.parseLong(getArg(args, "--retry-delay-ms", System.getenv().getOrDefault("BOT_RETRY_DELAY_MS", "700")));

            String seedArg = getArg(args, "--seed", "");
            Random random = seedArg.isBlank() ? new Random() : new Random(Long.parseLong(seedArg));

            return new Config(username, frontend, subEndpoint, timeoutMs, loginAttempts, retryDelayMs, random);
        }

        private static String getArg(String[] args, String key, String fallback) {
            for (int i = 0; i < args.length - 1; i++) {
                if (key.equals(args[i])) {
                    return args[i + 1];
                }
            }
            return fallback;
        }
    }
}
