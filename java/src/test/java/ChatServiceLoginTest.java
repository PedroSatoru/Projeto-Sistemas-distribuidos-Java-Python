import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import proto.ChatProtocol;

class ChatServiceLoginTest {

    @TempDir
    Path tempDir;

    @Test
    void shouldLoginWithRegisteredUser() throws Exception {
        ChatService service = createService();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginRequest(ChatProtocol.LoginRequest.newBuilder()
                        .setTimestampMs(System.currentTimeMillis())
                        .setUsername("java_bot_1")
                        .build())
                .build();

        ChatProtocol.ServerResponse response = service.handle(request);

        assertTrue(response.hasLoginResponse());
        assertTrue(response.getLoginResponse().getSuccess());
    }

    @Test
    void shouldRejectLoginWithInvalidUsernameFormat() throws Exception {
        ChatService service = createService();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginRequest(ChatProtocol.LoginRequest.newBuilder()
                        .setTimestampMs(System.currentTimeMillis())
                        .setUsername("user invalido")
                        .build())
                .build();

        ChatProtocol.ServerResponse response = service.handle(request);

        assertTrue(response.hasLoginResponse());
        assertFalse(response.getLoginResponse().getSuccess());
    }

    @Test
    void shouldRejectUnregisteredUser() throws Exception {
        ChatService service = createService();

        ChatProtocol.ClientRequest request = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginRequest(ChatProtocol.LoginRequest.newBuilder()
                        .setTimestampMs(System.currentTimeMillis())
                        .setUsername("unknown_user")
                        .build())
                .build();

        ChatProtocol.ServerResponse response = service.handle(request);

        assertTrue(response.hasLoginResponse());
        assertFalse(response.getLoginResponse().getSuccess());
    }

    @Test
    void shouldRejectDuplicatedLogin() throws Exception {
        ChatService service = createService();

        ChatProtocol.ClientRequest first = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginRequest(ChatProtocol.LoginRequest.newBuilder()
                        .setTimestampMs(System.currentTimeMillis())
                        .setUsername("java_bot_2")
                        .build())
                .build();

        ChatProtocol.ClientRequest second = ChatProtocol.ClientRequest.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginRequest(ChatProtocol.LoginRequest.newBuilder()
                        .setTimestampMs(System.currentTimeMillis())
                        .setUsername("java_bot_2")
                        .build())
                .build();

        ChatProtocol.ServerResponse firstResponse = service.handle(first);
        ChatProtocol.ServerResponse secondResponse = service.handle(second);

        assertTrue(firstResponse.getLoginResponse().getSuccess());
        assertFalse(secondResponse.getLoginResponse().getSuccess());
    }

    private ChatService createService() throws Exception {
        Path usersFile = tempDir.resolve("users.txt");
        Files.writeString(usersFile, "java_bot_1\njava_bot_2\nalice\n", StandardCharsets.UTF_8);

        PersistenceStore store = new PersistenceStore(
                tempDir.resolve("channels.txt"),
                tempDir.resolve("logins.txt")
        );

        return new ChatService(usersFile, store);
    }
}
