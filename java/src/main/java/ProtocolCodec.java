
import com.google.protobuf.InvalidProtocolBufferException;

import br.ufc.sd.chat.proto.ChatProtocol;

public final class ProtocolCodec {
    private ProtocolCodec() {
    }

    public static ChatProtocol.ClientRequest parseClientRequest(byte[] payload)
            throws InvalidProtocolBufferException {
        return ChatProtocol.ClientRequest.parseFrom(payload);
    }

    public static byte[] toBytes(ChatProtocol.ServerResponse response) {
        return response.toByteArray();
    }

    public static byte[] toBytes(ChatProtocol.ClientRequest request) {
        return request.toByteArray();
    }

    public static ChatProtocol.ServerResponse parseServerResponse(byte[] payload)
            throws InvalidProtocolBufferException {
        return ChatProtocol.ServerResponse.parseFrom(payload);
    }
}
