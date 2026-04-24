import java.nio.file.Path;

import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

import com.google.protobuf.InvalidProtocolBufferException;

import proto.ChatProtocol;

public class ChatServerMain {
    private static void log(String level, String id, String event, String message, long ts, long lc, int rank) {
        System.out.printf(
                "[ts=%d][lc=%d][lang=JAVA][role=SERVER][id=%s][rank=%d][lvl=%s][evt=%s] %s%n",
                ts,
                lc,
                id,
                rank,
                level,
                event,
                message
        );
    }

    private static long adjustedNowMs(long timeOffsetMs) {
        return System.currentTimeMillis() + timeOffsetMs;
    }

    public static void main(String[] args) {
        Config config = Config.from(args);
        LogicalClock logicalClock = new LogicalClock();
        long[] timeOffsetMs = new long[] { 0L };
        int[] rank = new int[] { 0 };
        int[] clientMessagesSinceHeartbeat = new int[] { 0 };

        PersistenceStore store = new PersistenceStore(config.channelsFile(), config.loginsFile(), config.messagesFile());
        ChatService service = new ChatService(config.usersFile(), store, () -> adjustedNowMs(timeOffsetMs[0]));

        try (ZContext context = new ZContext()) {
            ZMQ.Socket repSocket = context.createSocket(SocketType.REP);
            ZMQ.Socket pubSocket = context.createSocket(SocketType.PUB);
            repSocket.connect(config.backendEndpoint());
            pubSocket.connect(config.pubEndpoint());
            ReferenceServiceClient referenceClient = new ReferenceServiceClient(
                    context,
                    config.referenceEndpoint(),
                    config.referenceTimeoutMs()
            );

            log("INFO", config.serverId(), "CONNECT", "conectado em " + config.backendEndpoint(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            log("INFO", config.serverId(), "CONNECT", "publicando em " + config.pubEndpoint(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            log("INFO", config.serverId(), "USERS_FILE", config.usersFile().toString(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            log("INFO", config.serverId(), "CHANNELS_FILE", config.channelsFile().toString(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            log("INFO", config.serverId(), "LOGINS_FILE", config.loginsFile().toString(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            log("INFO", config.serverId(), "MESSAGES_FILE", config.messagesFile().toString(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);

            try {
                ReferenceServiceClient.ReferenceResult result = referenceClient.requestRank(
                        config.serverId(),
                        adjustedNowMs(timeOffsetMs[0])
                );
                rank[0] = result.rank();
                if (result.referenceTimeMs() > 0) {
                    timeOffsetMs[0] = result.referenceTimeMs() - System.currentTimeMillis();
                }
                log("INFO", config.serverId(), "RANK_OK", "rank=" + rank[0] + ", offset=" + timeOffsetMs[0] + "ms", adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            } catch (RuntimeException | InvalidProtocolBufferException ex) {
                log("WARN", config.serverId(), "RANK_FAIL", ex.getMessage(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
            }

            while (!Thread.currentThread().isInterrupted()) {
                byte[] raw = repSocket.recv(0);
                if (raw == null) {
                    continue;
                }

                ChatProtocol.ServerResponse response;
                try {
                    ChatProtocol.ClientRequest request = ProtocolCodec.parseClientRequest(raw);
                    logicalClock.update(request.getLogicalClock());
                    logRequest(config.serverId(), request, logicalClock.value(), rank[0]);
                    response = service.handle(request);

                    long responseLc = logicalClock.increment();
                    long responseTs = adjustedNowMs(timeOffsetMs[0]);
                    response = response.toBuilder()
                            .setTimestampMs(responseTs)
                            .setLogicalClock(responseLc)
                            .build();

                    ChatService.OutboundPublication publication = service.consumeLastPublication();
                    if (publication != null && response.hasPublishResponse() && response.getPublishResponse().getSuccess()) {
                        long pubLc = logicalClock.increment();
                        long pubTs = adjustedNowMs(timeOffsetMs[0]);
                        ChatProtocol.ChatMessage chatMessage = ChatProtocol.ChatMessage.newBuilder()
                                .setTimestampMs(pubTs)
                                .setChannelName(publication.channel())
                                .setUsername(publication.username())
                                .setMessageText(publication.messageText())
                                .setLogicalClock(pubLc)
                                .build();
                        byte[] topic = publication.channel().getBytes(java.nio.charset.StandardCharsets.UTF_8);
                        byte[] payload = ProtocolCodec.toBytes(chatMessage);
                        pubSocket.sendMore(topic);
                        pubSocket.send(payload);
                        log("INFO", config.serverId(), "PUB_SEND", "topic=" + publication.channel(), chatMessage.getTimestampMs(), logicalClock.value(), rank[0]);
                    }

                    clientMessagesSinceHeartbeat[0] += 1;
                    if (clientMessagesSinceHeartbeat[0] >= 10) {
                        clientMessagesSinceHeartbeat[0] = 0;
                        try {
                            ReferenceServiceClient.ReferenceResult hb = referenceClient.sendHeartbeat(
                                    config.serverId(),
                                    adjustedNowMs(timeOffsetMs[0])
                            );
                            if (hb.referenceTimeMs() > 0) {
                                timeOffsetMs[0] = hb.referenceTimeMs() - System.currentTimeMillis();
                            }
                            if (hb.rank() > 0) {
                                rank[0] = hb.rank();
                            }
                            log("INFO", config.serverId(), "HEARTBEAT_OK", "offset=" + timeOffsetMs[0] + "ms", adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
                        } catch (RuntimeException | InvalidProtocolBufferException ex) {
                            log("WARN", config.serverId(), "HEARTBEAT_FAIL", ex.getMessage(), adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0]);
                        }
                    }
                } catch (InvalidProtocolBufferException ex) {
                    response = ChatProtocol.ServerResponse.newBuilder()
                            .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                            .setLogicalClock(logicalClock.increment())
                            .setErrorResponse(
                                    ChatProtocol.ErrorResponse.newBuilder()
                                            .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                            .setError("Falha ao decodificar Protobuf")
                                            .build()
                            )
                            .build();
                } catch (RuntimeException ex) {
                    response = ChatProtocol.ServerResponse.newBuilder()
                            .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                            .setLogicalClock(logicalClock.increment())
                            .setErrorResponse(
                                    ChatProtocol.ErrorResponse.newBuilder()
                                            .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                            .setError("Erro interno: " + ex.getMessage())
                                            .build()
                            )
                            .build();
                }

                logResponse(config.serverId(), response, logicalClock.value(), rank[0]);
                repSocket.send(ProtocolCodec.toBytes(response), 0);
            }
        }
    }

    private static void logRequest(String serverId, ChatProtocol.ClientRequest request, long lc, int rank) {
        log("INFO", serverId, "RECV", "action=" + request.getActionCase(), request.getTimestampMs(), lc, rank);
    }

    private static void logResponse(String serverId, ChatProtocol.ServerResponse response, long lc, int rank) {
        log("INFO", serverId, "SEND", "action=" + response.getActionCase(), response.getTimestampMs(), lc, rank);
    }

    private record Config(
            String serverId,
            String backendEndpoint,
            String pubEndpoint,
                String referenceEndpoint,
                int referenceTimeoutMs,
            Path usersFile,
            Path channelsFile,
            Path loginsFile,
            Path messagesFile
    ) {
        private static Config from(String[] args) {
            String serverId = getArg(args, "--id", System.getenv().getOrDefault("SERVER_ID", "java_server"));
            String backend = getArg(args, "--backend", System.getenv().getOrDefault("BROKER_BACKEND_ENDPOINT", "tcp://broker:5556"));
            String pub = getArg(args, "--pub-endpoint", System.getenv().getOrDefault("PROXY_PUB_ENDPOINT", "tcp://python_proxy:5557"));
                String reference = getArg(args, "--reference-endpoint", System.getenv().getOrDefault("REFERENCE_ENDPOINT", "tcp://python_reference:5559"));
                int referenceTimeoutMs = Integer.parseInt(getArg(args, "--reference-timeout-ms", System.getenv().getOrDefault("REFERENCE_TIMEOUT_MS", "5000")));
            String users = getArg(args, "--users-file", System.getenv().getOrDefault("USERS_FILE", "/app/users.txt"));
            String dataDir = getArg(args, "--data-dir", System.getenv().getOrDefault("DATA_DIR", "/data"));

            return new Config(
                    serverId,
                    backend,
                    pub,
                    reference,
                    referenceTimeoutMs,
                    Path.of(users),
                    Path.of(dataDir, serverId + "_channels.txt"),
                    Path.of(dataDir, serverId + "_logins.txt"),
                    Path.of(dataDir, serverId + "_messages.txt")
            );
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
