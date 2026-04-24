import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;

import com.google.protobuf.InvalidProtocolBufferException;

import proto.ChatProtocol;

public class ReferenceServiceClient {
    private final ZMQ.Socket reqSocket;
    private final int timeoutMs;

    public record ReferenceResult(int rank, long referenceTimeMs) {
    }

    public ReferenceServiceClient(ZContext context, String endpoint, int timeoutMs) {
        this.timeoutMs = timeoutMs;
        this.reqSocket = context.createSocket(SocketType.REQ);
        this.reqSocket.setReceiveTimeOut(timeoutMs);
        this.reqSocket.connect(endpoint);
    }

    public ReferenceResult requestRank(String serverName, long timestampMs)
            throws InvalidProtocolBufferException {
        ChatProtocol.ReferenceRequest request = ChatProtocol.ReferenceRequest.newBuilder()
                .setTimestampMs(timestampMs)
                .setAction("rank")
                .setServerName(serverName)
                .build();

        ChatProtocol.ReferenceResponse response = sendAndReceive(request);
        return new ReferenceResult(response.getRank(), response.getReferenceTimeMs());
    }

    public ReferenceResult sendHeartbeat(String serverName, long timestampMs)
            throws InvalidProtocolBufferException {
        ChatProtocol.ReferenceRequest request = ChatProtocol.ReferenceRequest.newBuilder()
                .setTimestampMs(timestampMs)
                .setAction("heartbeat")
                .setServerName(serverName)
                .build();

        ChatProtocol.ReferenceResponse response = sendAndReceive(request);
        return new ReferenceResult(response.getRank(), response.getReferenceTimeMs());
    }

    public ChatProtocol.ReferenceResponse listServers(long timestampMs)
            throws InvalidProtocolBufferException {
        ChatProtocol.ReferenceRequest request = ChatProtocol.ReferenceRequest.newBuilder()
                .setTimestampMs(timestampMs)
                .setAction("list")
                .build();

        return sendAndReceive(request);
    }

    private ChatProtocol.ReferenceResponse sendAndReceive(ChatProtocol.ReferenceRequest request)
            throws InvalidProtocolBufferException {
        byte[] payload = request.toByteArray();
        reqSocket.send(payload, 0);
        byte[] raw = reqSocket.recv(0);
        if (raw == null) {
            throw new IllegalStateException("Timeout ao aguardar resposta do reference service em " + timeoutMs + "ms");
        }
        return ChatProtocol.ReferenceResponse.parseFrom(raw);
    }
}
