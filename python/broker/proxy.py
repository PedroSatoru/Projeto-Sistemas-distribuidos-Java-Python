import argparse
import zmq
import time


def log_event(level: str, event: str, message: str):
    ts_ms = int(time.time() * 1000)
    print(f"[ts={ts_ms}][PY-PROXY][{level}] {message}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="ZeroMQ Pub/Sub Proxy")
    parser.add_argument("--frontend", default="tcp://*:5557", help="Frontend (XSUB) endpoint (default: tcp://*:5557) - Servidores conectam PUB aqui")
    parser.add_argument("--backend", default="tcp://*:5558", help="Backend (XPUB) endpoint (default: tcp://*:5558) - Clientes conectam SUB aqui")
    args = parser.parse_args()

    context = zmq.Context()
    
    # XSUB accepts incoming messages from publishers
    xsub = context.socket(zmq.XSUB)
    
    # XPUB distributes messages to subscribers and passes subscriptions to XSUB
    xpub = context.socket(zmq.XPUB)

    xsub.bind(args.frontend)
    xpub.bind(args.backend)

    log_event("INFO", "BIND", f"xsub_frontend={args.frontend} xpub_backend={args.backend}")
    time.sleep(0.5)  # Allow broker to stabilize
    log_event("INFO", "READY", "proxy pub/sub pronto para rotear mensagens")

    try:
        zmq.proxy(xsub, xpub)
    except Exception as e:
        log_event("ERROR", "PROXY_CRASH", f"Proxy parou com erro: {e}")
    finally:
        xsub.close()
        xpub.close()
        context.term()


if __name__ == "__main__":
    main()
