import argparse
import zmq
import time


def log_event(level: str, event: str, message: str):
    ts_ms = int(time.time() * 1000)
    print(
        f"[ts={ts_ms}][lang=PY][role=BROKER][id=broker]"
        f"[lvl={level}][evt={event}] {message}",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description="ZeroMQ Router-Dealer Broker")
    parser.add_argument("--frontend", default="tcp://*:5555", help="Frontend endpoint (default: tcp://*:5555)")
    parser.add_argument("--backend", default="tcp://*:5556", help="Backend endpoint (default: tcp://*:5556)")
    args = parser.parse_args()

    context = zmq.Context()
    frontend = context.socket(zmq.ROUTER)
    backend = context.socket(zmq.DEALER)

    frontend.bind(args.frontend)
    backend.bind(args.backend)

    log_event("INFO", "BIND", f"frontend={args.frontend} backend={args.backend}")
    time.sleep(0.5)  # Allow broker to stabilize
    log_event("INFO", "READY", "pronto para aceitar conexoes")

    try:
        zmq.proxy(frontend, backend)
    finally:
        frontend.close()
        backend.close()
        context.term()


if __name__ == "__main__":
    main()
