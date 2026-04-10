import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import proto.ChatProtocol;

public class ChatService {
    private static final Pattern VALID_NAME = Pattern.compile("^[a-zA-Z0-9_-]+$");

    private final Set<String> allowedUsers;
    private final Set<String> activeUsers;
    private final Set<String> channels;
    private final PersistenceStore store;
    private OutboundPublication lastPublication;

    public record OutboundPublication(String channel, ChatProtocol.ChatMessage chatMessage) {
    }

    public ChatService(Path usersFile, PersistenceStore store) {
        this.allowedUsers = loadAllowedUsers(usersFile);
        this.activeUsers = new HashSet<>();
        this.store = store;
        this.channels = store.loadChannels();
    }

    public ChatProtocol.ServerResponse handle(ChatProtocol.ClientRequest request) {
        return switch (request.getActionCase()) {
            case LOGIN_REQUEST -> handleLogin(request.getLoginRequest());
            case LIST_CHANNELS_REQUEST -> handleListChannels();
            case CREATE_CHANNEL_REQUEST -> handleCreateChannel(request.getCreateChannelRequest());
            case PUBLISH_REQUEST -> handlePublish(request.getPublishRequest());
            case ACTION_NOT_SET -> error("Mensagem sem acao definida");
        };
    }

    public synchronized OutboundPublication consumeLastPublication() {
        OutboundPublication value = lastPublication;
        lastPublication = null;
        return value;
    }

    private ChatProtocol.ServerResponse handleLogin(ChatProtocol.LoginRequest request) {
        String username = request.getUsername().trim();

        if (!VALID_NAME.matcher(username).matches()) {
            return loginResponse(false, "Formato de nome de usuario invalido.");
        }

        String normalized = username.toLowerCase();
        if (!allowedUsers.contains(normalized)) {
            return loginResponse(false, "Usuario nao registrado.");
        }

        synchronized (activeUsers) {
            if (activeUsers.contains(normalized)) {
                return loginResponse(false, "Usuario ja conectado.");
            }
            activeUsers.add(normalized);
        }

        long now = System.currentTimeMillis();
        store.appendLogin(now, username);
        return loginResponse(true, "");
    }

    private ChatProtocol.ServerResponse handleListChannels() {
        List<String> ordered;
        synchronized (channels) {
            ordered = new ArrayList<>(channels);
            ordered.sort(String::compareTo);
        }

        ChatProtocol.ListChannelsResponse response = ChatProtocol.ListChannelsResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .addAllChannels(ordered)
                .build();

        return ChatProtocol.ServerResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setListChannelsResponse(response)
                .build();
    }

    private ChatProtocol.ServerResponse handleCreateChannel(ChatProtocol.CreateChannelRequest request) {
        String channelName = request.getChannelName().trim();

        if (!VALID_NAME.matcher(channelName).matches()) {
            return createChannelResponse(false, "Formato de nome de canal invalido.");
        }

        String normalized = channelName.toLowerCase();
        synchronized (channels) {
            if (channels.contains(normalized)) {
                return createChannelResponse(false, "Canal ja existe.");
            }
            channels.add(normalized);
            store.persistChannelSet(channels);
        }

        return createChannelResponse(true, "");
    }

    private ChatProtocol.ServerResponse handlePublish(ChatProtocol.PublishRequest request) {
        String channelName = request.getChannelName().trim().toLowerCase();
        String messageText = request.getMessageText();
        String username = request.getUsername().trim();

        if (!VALID_NAME.matcher(channelName).matches()) {
            return publishResponse(false, "Formato de nome de canal invalido.");
        }

        if (messageText == null || messageText.isBlank()) {
            return publishResponse(false, "Mensagem vazia nao permitida.");
        }

        if (!username.isEmpty() && !VALID_NAME.matcher(username).matches()) {
            return publishResponse(false, "Formato de nome de usuario invalido.");
        }

        String publicationUser = username.isEmpty() ? "unknown" : username;
        synchronized (channels) {
            if (!channels.contains(channelName)) {
                return publishResponse(false, "Canal nao existe.");
            }
        }

        long now = request.getTimestampMs() > 0 ? request.getTimestampMs() : System.currentTimeMillis();
        ChatProtocol.ChatMessage chatMessage = ChatProtocol.ChatMessage.newBuilder()
                .setTimestampMs(now)
                .setChannelName(channelName)
                .setUsername(publicationUser)
                .setMessageText(messageText)
                .build();

        store.appendPublishedMessage(now, publicationUser, channelName, messageText);
        synchronized (this) {
            lastPublication = new OutboundPublication(channelName, chatMessage);
        }
        return publishResponse(true, "");
    }

    private ChatProtocol.ServerResponse loginResponse(boolean success, String error) {
        ChatProtocol.LoginResponse response = ChatProtocol.LoginResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setSuccess(success)
                .setError(error)
                .build();

        return ChatProtocol.ServerResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setLoginResponse(response)
                .build();
    }

    private ChatProtocol.ServerResponse createChannelResponse(boolean success, String error) {
        ChatProtocol.CreateChannelResponse response = ChatProtocol.CreateChannelResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setSuccess(success)
                .setError(error)
                .build();

        return ChatProtocol.ServerResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setCreateChannelResponse(response)
                .build();
    }

    private ChatProtocol.ServerResponse publishResponse(boolean success, String error) {
        ChatProtocol.PublishResponse response = ChatProtocol.PublishResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setSuccess(success)
                .setError(error)
                .build();

        return ChatProtocol.ServerResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setPublishResponse(response)
                .build();
    }

    private ChatProtocol.ServerResponse error(String message) {
        ChatProtocol.ErrorResponse response = ChatProtocol.ErrorResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setError(message)
                .build();

        return ChatProtocol.ServerResponse.newBuilder()
                .setTimestampMs(System.currentTimeMillis())
                .setErrorResponse(response)
                .build();
    }

    private Set<String> loadAllowedUsers(Path usersFile) {
        if (!Files.exists(usersFile)) {
            throw new IllegalStateException("Arquivo de usuarios nao encontrado: " + usersFile);
        }

        try {
            Set<String> users = new HashSet<>();
            for (String line : Files.readAllLines(usersFile, StandardCharsets.UTF_8)) {
                String value = line.trim().toLowerCase();
                if (!value.isEmpty()) {
                    users.add(value);
                }
            }
            return users;
        } catch (IOException ex) {
            throw new IllegalStateException("Falha ao carregar usuarios de " + usersFile, ex);
        }
    }
}
