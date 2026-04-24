public class LogicalClock {
    private long counter;

    public synchronized long increment() {
        counter += 1;
        return counter;
    }

    public synchronized long update(long received) {
        counter = Math.max(counter, received) + 1;
        return counter;
    }

    public synchronized long value() {
        return counter;
    }
}
