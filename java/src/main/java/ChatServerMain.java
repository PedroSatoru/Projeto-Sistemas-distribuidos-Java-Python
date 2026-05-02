import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;
import org.zeromq.ZMsg;

import com.google.protobuf.InvalidProtocolBufferException;

import proto.ChatProtocol;

public class ChatServerMain {
    private static void log(String level, String id, String event, String message, long ts, long lc, int rank, String coordinator) {
        System.out.printf(
                "[ts=%d][lc=%d][lang=JAVA][role=SERVER][id=%s][rank=%d][coord=%s][lvl=%s][evt=%s] %s%n",
                ts, lc, id, rank, coordinator, level, event, message);
    }

    private static long adjustedNowMs(long timeOffsetMs) {
        return System.currentTimeMillis() + timeOffsetMs;
    }

    public static void main(String[] args) {
        Config config = Config.from(args);
        LogicalClock logicalClock = new LogicalClock();
        long[] timeOffsetMs = new long[]{0L};
        int[] rank = new int[]{0};
        int[] clientMsgCount = new int[]{0};
        AtomicReference<String> coordinatorName = new AtomicReference<>("NONE");
        String electionEndpoint = "tcp://" + config.serverId() + ":" + config.electionPort();

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

            // Part 4: Election REP socket
            ZMQ.Socket electionSocket = context.createSocket(SocketType.REP);
            electionSocket.bind("tcp://*:" + config.electionPort());
            log("INFO", config.serverId(), "ELECTION_BIND", "porta " + config.electionPort(),
                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());

            // Part 4: SUB for coordinator announcements
            ZMQ.Socket serversSub = context.createSocket(SocketType.SUB);
            serversSub.connect(config.subEndpoint());
            serversSub.subscribe("servers".getBytes(StandardCharsets.UTF_8));

            log("INFO", config.serverId(), "CONNECT", "backend=" + config.backendEndpoint(),
                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());

            try {
                ReferenceServiceClient.ReferenceResult result = referenceClient.requestRank(
                        config.serverId(), adjustedNowMs(timeOffsetMs[0]), electionEndpoint);
                rank[0] = result.rank();
                if (result.referenceTimeMs() > 0) {
                    timeOffsetMs[0] = result.referenceTimeMs() - System.currentTimeMillis();
                }
                log("INFO", config.serverId(), "RANK_OK", "rank=" + rank[0] + " offset=" + timeOffsetMs[0] + "ms",
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());
            } catch (RuntimeException | InvalidProtocolBufferException ex) {
                log("WARN", config.serverId(), "RANK_FAIL", ex.getMessage(),
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());
            }

            // Part 4: Coordinator announcement listener thread
            Thread coordThread = new Thread(() -> {
                while (!Thread.currentThread().isInterrupted()) {
                    try {
                        ZMsg frames = ZMsg.recvMsg(serversSub, ZMQ.DONTWAIT);
                        if (frames == null) { Thread.sleep(500); continue; }
                        if (frames.size() >= 2) {
                            ChatProtocol.CoordinatorAnnouncement ann =
                                    ChatProtocol.CoordinatorAnnouncement.parseFrom(frames.getLast().getData());
                            coordinatorName.set(ann.getCoordinatorName());
                            log("INFO", config.serverId(), "COORDINATOR_UPDATE",
                                    "novo coordenador: " + ann.getCoordinatorName(),
                                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());
                        }
                        frames.destroy();
                    } catch (Exception ignored) {}
                }
            }, "coord-listener");
            coordThread.setDaemon(true);
            coordThread.start();

            // Part 4: Initial election after delay
            final int myRank = rank[0];
            new Thread(() -> {
                try { Thread.sleep(5000); } catch (InterruptedException ignored) {}
                startElection(context, config.serverId(), myRank, coordinatorName,
                        referenceClient, pubSocket, timeOffsetMs, logicalClock, electionEndpoint);
            }, "initial-election").start();

            // Part 4: Poller for repSocket + electionSocket
            ZMQ.Poller poller = context.createPoller(2);
            poller.register(repSocket, ZMQ.Poller.POLLIN);
            poller.register(electionSocket, ZMQ.Poller.POLLIN);

            while (!Thread.currentThread().isInterrupted()) {
                poller.poll(1000);

                // Handle election/clock sync on election socket
                if (poller.pollin(1)) {
                    byte[] eraw = electionSocket.recv(0);
                    if (eraw != null) {
                        handleElectionOrClockSync(electionSocket, eraw, config.serverId(), rank[0],
                                coordinatorName, timeOffsetMs, logicalClock, context,
                                referenceClient, pubSocket, electionEndpoint);
                    }
                }

                // Handle client requests on repSocket
                if (poller.pollin(0)) {
                    byte[] raw = repSocket.recv(0);
                    if (raw == null) continue;

                    ChatProtocol.ServerResponse response;
                    try {
                        ChatProtocol.ClientRequest request = ProtocolCodec.parseClientRequest(raw);
                        logicalClock.update(request.getLogicalClock());
                        logRequest(config.serverId(), request, logicalClock.value(), rank[0], coordinatorName.get());
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
                            byte[] topic = publication.channel().getBytes(StandardCharsets.UTF_8);
                            byte[] payload = ProtocolCodec.toBytes(chatMessage);
                            pubSocket.sendMore(topic);
                            pubSocket.send(payload);
                        }

                        // Part 4: every 15 msgs -> heartbeat + clock sync
                        clientMsgCount[0] += 1;
                        if (clientMsgCount[0] >= 15) {
                            clientMsgCount[0] = 0;
                            try {
                                referenceClient.sendHeartbeat(config.serverId(),
                                        adjustedNowMs(timeOffsetMs[0]), electionEndpoint);
                                log("INFO", config.serverId(), "HEARTBEAT_OK", "heartbeat enviado",
                                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());
                            } catch (Exception ex) {
                                log("WARN", config.serverId(), "HEARTBEAT_FAIL", ex.getMessage(),
                                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank[0], coordinatorName.get());
                            }
                            syncClockWithCoordinator(context, config.serverId(), rank[0],
                                    coordinatorName, referenceClient, timeOffsetMs, logicalClock, electionEndpoint);
                        }
                    } catch (InvalidProtocolBufferException ex) {
                        response = ChatProtocol.ServerResponse.newBuilder()
                                .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                .setLogicalClock(logicalClock.increment())
                                .setErrorResponse(ChatProtocol.ErrorResponse.newBuilder()
                                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                        .setError("Falha ao decodificar Protobuf").build())
                                .build();
                    } catch (RuntimeException ex) {
                        response = ChatProtocol.ServerResponse.newBuilder()
                                .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                .setLogicalClock(logicalClock.increment())
                                .setErrorResponse(ChatProtocol.ErrorResponse.newBuilder()
                                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                        .setError("Erro interno: " + ex.getMessage()).build())
                                .build();
                    }

                    logResponse(config.serverId(), response, logicalClock.value(), rank[0], coordinatorName.get());
                    repSocket.send(ProtocolCodec.toBytes(response), 0);
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // Part 4: Election + Clock Sync helpers
    // ------------------------------------------------------------------

    private static void handleElectionOrClockSync(
            ZMQ.Socket electionSocket, byte[] raw, String serverId, int rank,
            AtomicReference<String> coordinatorName, long[] timeOffsetMs,
            LogicalClock logicalClock, ZContext context,
            ReferenceServiceClient referenceClient, ZMQ.Socket pubSocket,
            String electionEndpoint) {
        // Distinguish: ClockSyncRequest has local_time_ms > 1 trillion; ElectionRequest has rank (small int)
        try {
            ChatProtocol.ClockSyncRequest csreq = ChatProtocol.ClockSyncRequest.parseFrom(raw);
            if (!csreq.getServerName().isEmpty() && csreq.getLocalTimeMs() > 1_000_000_000_000L) {
                ChatProtocol.ClockSyncResponse resp = ChatProtocol.ClockSyncResponse.newBuilder()
                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                        .setCorrectTimeMs(adjustedNowMs(timeOffsetMs[0]))
                        .build();
                electionSocket.send(resp.toByteArray(), 0);
                log("INFO", serverId, "CLOCK_SYNC_RESP", "hora enviada para " + csreq.getServerName(),
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
                return;
            }
        } catch (Exception ignored) {}

        // Election request
        try {
            ChatProtocol.ElectionRequest req = ChatProtocol.ElectionRequest.parseFrom(raw);
            log("INFO", serverId, "ELECTION_RECV", "de " + req.getServerName() + " rank=" + req.getRank(),
                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
            ChatProtocol.ElectionResponse resp = ChatProtocol.ElectionResponse.newBuilder()
                    .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                    .setServerName(serverId).setOk(true).build();
            electionSocket.send(resp.toByteArray(), 0);
            if (rank > req.getRank()) {
                new Thread(() -> startElection(context, serverId, rank, coordinatorName,
                        referenceClient, pubSocket, timeOffsetMs, logicalClock, electionEndpoint),
                        "election-cascade").start();
            }
        } catch (Exception e) {
            try {
                ChatProtocol.ElectionResponse resp = ChatProtocol.ElectionResponse.newBuilder()
                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                        .setServerName(serverId).setOk(true).build();
                electionSocket.send(resp.toByteArray(), 0);
            } catch (Exception ignored) {}
        }
    }

    private static void startElection(ZContext context, String serverId, int rank,
            AtomicReference<String> coordinatorName, ReferenceServiceClient referenceClient,
            ZMQ.Socket pubSocket, long[] timeOffsetMs, LogicalClock logicalClock, String electionEndpoint) {
        log("INFO", serverId, "ELECTION_START", "rank=" + rank,
                adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
        try {
            ChatProtocol.ReferenceResponse listResp = referenceClient.listServers(adjustedNowMs(timeOffsetMs[0]));
            List<ChatProtocol.ServerInfo> servers = listResp.getServersList();
            boolean gotOk = false;
            for (ChatProtocol.ServerInfo s : servers) {
                if (s.getRank() > rank && !s.getName().equals(serverId)) {
                    String ep = s.getElectionEndpoint();
                    if (ep.isEmpty()) continue;
                    try (ZContext tmpCtx = new ZContext()) {
                        ZMQ.Socket sock = tmpCtx.createSocket(SocketType.REQ);
                        sock.setReceiveTimeOut(3000);
                        sock.setLinger(0);
                        sock.connect(ep);
                        ChatProtocol.ElectionRequest req = ChatProtocol.ElectionRequest.newBuilder()
                                .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                                .setServerName(serverId).setRank(rank).build();
                        sock.send(req.toByteArray(), 0);
                        byte[] respRaw = sock.recv(0);
                        if (respRaw != null) {
                            ChatProtocol.ElectionResponse resp = ChatProtocol.ElectionResponse.parseFrom(respRaw);
                            if (resp.getOk()) {
                                log("INFO", serverId, "ELECTION_OK_RECV", s.getName() + " respondeu OK",
                                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
                                gotOk = true;
                            }
                        }
                    } catch (Exception ignored) {}
                }
            }
            if (!gotOk) {
                coordinatorName.set(serverId);
                log("INFO", serverId, "COORDINATOR_SELF", "EU sou o coordenador",
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
                ChatProtocol.CoordinatorAnnouncement ann = ChatProtocol.CoordinatorAnnouncement.newBuilder()
                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                        .setCoordinatorName(serverId).build();
                pubSocket.sendMore("servers");
                pubSocket.send(ann.toByteArray(), 0);
                log("INFO", serverId, "COORDINATOR_PUB", "anuncio publicado no topico 'servers'",
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
            } else {
                log("INFO", serverId, "ELECTION_WAIT", "aguardando coordenador",
                        adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
            }
        } catch (Exception e) {
            log("WARN", serverId, "ELECTION_FAIL", e.getMessage(),
                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
        }
    }

    private static void syncClockWithCoordinator(ZContext context, String serverId, int rank,
            AtomicReference<String> coordinatorName, ReferenceServiceClient referenceClient,
            long[] timeOffsetMs, LogicalClock logicalClock, String electionEndpoint) {
        String coord = coordinatorName.get();
        if ("NONE".equals(coord) || coord == null) return;
        if (coord.equals(serverId)) return;

        try {
            ChatProtocol.ReferenceResponse listResp = referenceClient.listServers(adjustedNowMs(timeOffsetMs[0]));
            String coordEp = null;
            for (ChatProtocol.ServerInfo s : listResp.getServersList()) {
                if (s.getName().equals(coord)) { coordEp = s.getElectionEndpoint(); break; }
            }
            if (coordEp == null || coordEp.isEmpty()) return;
            try (ZContext tmpCtx = new ZContext()) {
                ZMQ.Socket sock = tmpCtx.createSocket(SocketType.REQ);
                sock.setReceiveTimeOut(3000);
                sock.setLinger(0);
                sock.connect(coordEp);
                ChatProtocol.ClockSyncRequest req = ChatProtocol.ClockSyncRequest.newBuilder()
                        .setTimestampMs(adjustedNowMs(timeOffsetMs[0]))
                        .setServerName(serverId)
                        .setLocalTimeMs(adjustedNowMs(timeOffsetMs[0])).build();
                sock.send(req.toByteArray(), 0);
                byte[] respRaw = sock.recv(0);
                if (respRaw != null) {
                    ChatProtocol.ClockSyncResponse resp = ChatProtocol.ClockSyncResponse.parseFrom(respRaw);
                    if (resp.getCorrectTimeMs() > 0) {
                        timeOffsetMs[0] = resp.getCorrectTimeMs() - System.currentTimeMillis();
                        log("INFO", serverId, "CLOCK_SYNC_OK", "sincronizado com " + coord + " offset=" + timeOffsetMs[0] + "ms",
                                adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
                    }
                }
            }
        } catch (Exception e) {
            log("WARN", serverId, "CLOCK_SYNC_FAIL", coord + " nao respondeu",
                    adjustedNowMs(timeOffsetMs[0]), logicalClock.value(), rank, coordinatorName.get());
            startElection(context, serverId, rank, coordinatorName, referenceClient,
                    null, timeOffsetMs, logicalClock, electionEndpoint);
        }
    }

    private static void logRequest(String serverId, ChatProtocol.ClientRequest request, long lc, int rank, String coordinator) {
        log("INFO", serverId, "RECV", "action=" + request.getActionCase(), request.getTimestampMs(), lc, rank, coordinator);
    }

    private static void logResponse(String serverId, ChatProtocol.ServerResponse response, long lc, int rank, String coordinator) {
        log("INFO", serverId, "SEND", "action=" + response.getActionCase(), response.getTimestampMs(), lc, rank, coordinator);
    }

    private record Config(
            String serverId,
            String backendEndpoint,
            String pubEndpoint,
            String subEndpoint,
            String referenceEndpoint,
            int referenceTimeoutMs,
            int electionPort,
            Path usersFile,
            Path channelsFile,
            Path loginsFile,
            Path messagesFile
    ) {
        private static Config from(String[] args) {
            String serverId = getArg(args, "--id", System.getenv().getOrDefault("SERVER_ID", "java_server"));
            String backend = getArg(args, "--backend", System.getenv().getOrDefault("BROKER_BACKEND_ENDPOINT", "tcp://broker:5556"));
            String pub = getArg(args, "--pub-endpoint", System.getenv().getOrDefault("PROXY_PUB_ENDPOINT", "tcp://python_proxy:5557"));
            String sub = getArg(args, "--sub-endpoint", System.getenv().getOrDefault("PROXY_SUB_ENDPOINT", "tcp://python_proxy:5558"));
            String reference = getArg(args, "--reference-endpoint", System.getenv().getOrDefault("REFERENCE_ENDPOINT", "tcp://python_reference:5559"));
            int referenceTimeoutMs = Integer.parseInt(getArg(args, "--reference-timeout-ms", System.getenv().getOrDefault("REFERENCE_TIMEOUT_MS", "5000")));
            int electionPort = Integer.parseInt(getArg(args, "--election-port", System.getenv().getOrDefault("ELECTION_PORT", "6003")));
            String users = getArg(args, "--users-file", System.getenv().getOrDefault("USERS_FILE", "/app/users.txt"));
            String dataDir = getArg(args, "--data-dir", System.getenv().getOrDefault("DATA_DIR", "/data"));

            return new Config(
                    serverId, backend, pub, sub, reference, referenceTimeoutMs, electionPort,
                    Path.of(users),
                    Path.of(dataDir, serverId + "_channels.txt"),
                    Path.of(dataDir, serverId + "_logins.txt"),
                    Path.of(dataDir, serverId + "_messages.txt")
            );
        }

        private static String getArg(String[] args, String key, String fallback) {
            for (int i = 0; i < args.length - 1; i++) {
                if (key.equals(args[i])) return args[i + 1];
            }
            return fallback;
        }
    }
}
