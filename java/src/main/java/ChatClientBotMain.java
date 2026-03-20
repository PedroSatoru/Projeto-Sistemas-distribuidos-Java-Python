import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

import com.google.protobuf.InvalidProtocolBufferException;

import br.ufc.sd.chat.proto.ChatProtocol;

public class ChatClientBotMain {
    private static void log(String level, String id, String event, String message) {
        long ts = System.currentTimeMillis();
        System.out.printf("[ts=%d][JAVA-CLIENT][%s][%s] %s: %s%n", ts, id, level, event, message);
    }

    private static void log(String level, String id, String event, String message, long messageTs) {
        System.out.printf("[ts=%d][JAVA-CLIENT][%s][%s] %s: %s%n", messageTs, id, level, event, message);
    }

    public static void main(String[] args) throws InterruptedException {
        Config config = Config.from(args);

        try (ZContext context = new ZContext()) {
            ZMQ.Socket socket = context.createSocket(SocketType.REQ);
            socket.connect(config.frontendEndpoint());
            socket.setReceiveTimeOut(config.timeoutMs());

            log("INFO", config.username(), "CONNECT", "conectado em " + config.frontendEndpoint());

            if (!loginWithRetry(socket, config.username(), config.loginAttempts(), config.retryDelayMs())) {
                log("ERROR", config.username(), "LOGIN_FAIL", "login falhou apos " + config.loginAttempts() + " tentativas");
                return;
            }

            listChannels(socket, config.username());
            createChannels(socket, config.username(), config.channels());
            listChannels(socket, config.username());
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
            Thread.sleep(retryDelayMs);
        }
        return false;
    }

    private static void listChannels(ZMQ.Socket socket, String username) {
        ChatProtocol.ListChannelsRequest listRequest = ChatProtocol.ListChannelsRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .build();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setListChannelsRequest(listRequest)
                .build();

        ChatProtocol.ServerResponse response = sendAndReceive(socket, request, username, "LIST_CHANNELS");
        if (response == null) {
            return;
        }

        if (response.hasListChannelsResponse()) {
            log("INFO", username, "LIST_CHANNELS_OK", "canais=" + response.getListChannelsResponse().getChannelsList());
        } else {
            log("ERROR", username, "LIST_CHANNELS_FAIL", response.getErrorResponse().getError());
        }
    }

    private static void createChannels(ZMQ.Socket socket, String username, List<String> channels) {
        for (String channel : channels) {
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
                continue;
            }

            if (response.hasCreateChannelResponse() && response.getCreateChannelResponse().getSuccess()) {
                log("INFO", username, "CREATE_CHANNEL_OK", "canal criado: " + channel);
            } else if (response.hasCreateChannelResponse()) {
                log("WARN", username, "CREATE_CHANNEL_FAIL", "falha ao criar canal " + channel + ": " + response.getCreateChannelResponse().getError());
            } else {
                log("ERROR", username, "CREATE_CHANNEL_FAIL", "erro ao criar canal " + channel + ": " + response.getErrorResponse().getError());
            }
        }
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
            List<String> channels,
            int timeoutMs,
            int loginAttempts,
            long retryDelayMs
    ) {
        static Config from(String[] args) {
            String username = getArg(args, "--username", System.getenv().getOrDefault("BOT_USERNAME", "java_bot_1"));
            String frontend = getArg(args, "--frontend", System.getenv().getOrDefault("BROKER_FRONTEND_ENDPOINT", "tcp://broker:5555"));
            String channelList = getArg(args, "--channels", System.getenv().getOrDefault("BOT_CHANNELS", "general,random,announcements"));
            int timeoutMs = Integer.parseInt(getArg(args, "--timeout-ms", System.getenv().getOrDefault("BOT_TIMEOUT_MS", "5000")));
            int loginAttempts = Integer.parseInt(getArg(args, "--login-attempts", System.getenv().getOrDefault("BOT_LOGIN_ATTEMPTS", "3")));
            long retryDelayMs = Long.parseLong(getArg(args, "--retry-delay-ms", System.getenv().getOrDefault("BOT_RETRY_DELAY_MS", "700")));

            List<String> channels = Arrays.stream(channelList.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .collect(Collectors.toList());

            return new Config(username, frontend, channels, timeoutMs, loginAttempts, retryDelayMs);
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
