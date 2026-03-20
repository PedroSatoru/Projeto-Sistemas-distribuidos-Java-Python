import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class PersistenceStore {
    private final Path channelsFile;
    private final Path loginsFile;

    public PersistenceStore(Path channelsFile, Path loginsFile) {
        this.channelsFile = channelsFile;
        this.loginsFile = loginsFile;
    }

    public Set<String> loadChannels() {
        if (!Files.exists(channelsFile)) {
            return new HashSet<>();
        }

        try {
            Set<String> channels = new HashSet<>();
            for (String line : Files.readAllLines(channelsFile, StandardCharsets.UTF_8)) {
                String value = line.trim().toLowerCase();
                if (!value.isEmpty()) {
                    channels.add(value);
                }
            }
            return channels;
        } catch (IOException ex) {
            throw new IllegalStateException("Falha ao carregar canais de " + channelsFile, ex);
        }
    }

    public synchronized void appendLogin(long timestampMs, String username) {
        String line = timestampMs + "|" + username + System.lineSeparator();
        appendLine(loginsFile, line);
    }

    public synchronized void persistChannelSet(Set<String> channels) {
        List<String> ordered = new ArrayList<>(channels);
        ordered.sort(Comparator.naturalOrder());
        try {
            Files.createDirectories(channelsFile.getParent());
            Files.write(
                    channelsFile,
                    ordered,
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE
            );
        } catch (IOException ex) {
            throw new IllegalStateException("Falha ao persistir canais em " + channelsFile, ex);
        }
    }

    private void appendLine(Path file, String line) {
        try {
            Files.createDirectories(file.getParent());
            Files.writeString(
                    file,
                    line,
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.APPEND,
                    StandardOpenOption.WRITE
            );
        } catch (IOException ex) {
            throw new IllegalStateException("Falha ao escrever em " + file, ex);
        }
    }
}
