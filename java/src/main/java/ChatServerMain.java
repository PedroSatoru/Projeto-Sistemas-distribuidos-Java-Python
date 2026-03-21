import java.nio.file.Path;

import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

import com.google.protobuf.InvalidProtocolBufferException;

import proto.ChatProtocol;

public class ChatServerMain {
    private static void log(String level, String id, String event, String message) {
        long ts = System.currentTimeMillis();
        System.out.printf("[ts=%d][JAVA-SERVER][%s][%s] %s: %s%n", ts, id, level, event, message);
    }

    private static void log(String level, String id, String event, String message, long messageTs) {
        System.out.printf("[ts=%d][JAVA-SERVER][%s][%s] %s: %s%n", messageTs, id, level, event, message);
    }

    public static void main(String[] args) {
        Config config = Config.from(args);

        PersistenceStore store = new PersistenceStore(config.channelsFile(), config.loginsFile());
        ChatService service = new ChatService(config.usersFile(), store);

        try (ZContext context = new ZContext()) {
            ZMQ.Socket socket = context.createSocket(SocketType.REP);
            socket.connect(config.backendEndpoint());

            log("INFO", config.serverId(), "CONNECT", "conectado em " + config.backendEndpoint());
            log("INFO", config.serverId(), "USERS_FILE", config.usersFile().toString());
            log("INFO", config.serverId(), "CHANNELS_FILE", config.channelsFile().toString());
            log("INFO", config.serverId(), "LOGINS_FILE", config.loginsFile().toString());

            while (!Thread.currentThread().isInterrupted()) {
                byte[] raw = socket.recv(0);
                if (raw == null) {
                    continue;
                }

                ChatProtocol.ServerResponse response;
                try {
                    ChatProtocol.ClientRequest request = ProtocolCodec.parseClientRequest(raw);
                    logRequest(config.serverId(), request);
                    response = service.handle(request);
                } catch (InvalidProtocolBufferException ex) {
                    response = ChatProtocol.ServerResponse.newBuilder()
                            .setTimestampMs(System.currentTimeMillis())
                            .setErrorResponse(
                                    ChatProtocol.ErrorResponse.newBuilder()
                                            .setTimestampMs(System.currentTimeMillis())
                                            .setError("Falha ao decodificar Protobuf")
                                            .build()
                            )
                            .build();
                } catch (RuntimeException ex) {
                    response = ChatProtocol.ServerResponse.newBuilder()
                            .setTimestampMs(System.currentTimeMillis())
                            .setErrorResponse(
                                    ChatProtocol.ErrorResponse.newBuilder()
                                            .setTimestampMs(System.currentTimeMillis())
                                            .setError("Erro interno: " + ex.getMessage())
                                            .build()
                            )
                            .build();
                }

                logResponse(config.serverId(), response);
                socket.send(ProtocolCodec.toBytes(response), 0);
            }
        }
    }

    private static void logRequest(String serverId, ChatProtocol.ClientRequest request) {
        log("INFO", serverId, "RECV", "action=" + request.getActionCase(), request.getTimestampMs());
    }

    private static void logResponse(String serverId, ChatProtocol.ServerResponse response) {
        log("INFO", serverId, "SEND", "action=" + response.getActionCase(), response.getTimestampMs());
    }

    private record Config(
            String serverId,
            String backendEndpoint,
            Path usersFile,
            Path channelsFile,
            Path loginsFile
    ) {
        private static Config from(String[] args) {
            String serverId = getArg(args, "--id", System.getenv().getOrDefault("SERVER_ID", "java_server"));
            String backend = getArg(args, "--backend", System.getenv().getOrDefault("BROKER_BACKEND_ENDPOINT", "tcp://broker:5556"));
            String users = getArg(args, "--users-file", System.getenv().getOrDefault("USERS_FILE", "/app/users.txt"));
            String dataDir = getArg(args, "--data-dir", System.getenv().getOrDefault("DATA_DIR", "/data"));

            return new Config(
                    serverId,
                    backend,
                    Path.of(users),
                    Path.of(dataDir, serverId + "_channels.txt"),
                    Path.of(dataDir, serverId + "_logins.txt")
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
