# Sistema de Chat Distribuido - Parte 1

Implementacao da Parte 1 do projeto de Sistemas Distribuidos com interoperabilidade entre Python e Java.

## Visao geral

A arquitetura atual usa um unico broker Python para todo o sistema. Clientes e servidores de ambas as linguagens usam o mesmo protocolo binario e a mesma topologia de rede.

Topologia em execucao:

- 1 broker Python (ROUTER/DEALER)
- 2 servidores Python (REP no backend do broker)
- 2 servidores Java (REP no backend do broker)
- 2 clientes Python (REQ no frontend do broker)
- 2 clientes Java (REQ no frontend do broker)

## Tecnologias e decisoes

- Comunicacao: ZeroMQ
- Padrao: Request-Reply com broker ROUTER/DEALER
- Serializacao: Protocol Buffers (unificado entre Python e Java)
- Timestamp: todas as mensagens incluem `timestamp_ms`
- Persistencia:
  - Python: JSON por servidor em `python/data/`
  - Java: arquivos texto por servidor em `java/data/`

## Contrato de mensagens

Schema Protobuf:

- `python/proto/chat.proto`
- `java/src/main/proto/chat.proto`

Mensagens principais:

- `ClientRequest` com `oneof` para:
  - `login_request`
  - `list_channels_request`
  - `create_channel_request`
- `ServerResponse` com `oneof` para:
  - `login_response`
  - `list_channels_response`
  - `create_channel_response`
  - `error_response`

## Fluxo funcional da Parte 1

Cada cliente executa automaticamente:

1. Login
2. Listagem de canais
3. Criacao de canais
4. Listagem final de canais

Os servidores validam:

- formato de username e canal
- existencia de usuario permitido
- duplicidade de login
- duplicidade de canal

## Estrutura relevante do projeto

```text
python/
  broker/broker.py
  client/client.py
  server/server.py
  schemas/messages.py
  proto/chat.proto
  users.txt

java/
  src/main/java/
    ChatClientBotMain.java
    ChatServerMain.java
    ChatService.java
    ProtocolCodec.java
    PersistenceStore.java
  src/main/proto/chat.proto

docker-compose.yaml
```

## Como executar

Subir todo o ambiente:

```bash
docker compose up --build
```

Parar e remover containers:

```bash
docker compose down
```

## Interoperabilidade (o que esperar)

Com o ambiente em execucao:

- cliente Python pode ser atendido por servidor Python ou Java
- cliente Java pode ser atendido por servidor Java ou Python

Isso acontece porque todos os clientes vao para o mesmo frontend do broker e todos os servidores vao para o mesmo backend.

## Execucao local sem Docker (opcional)

### Python

```bash
cd python
pip install -r requirements.txt
python broker/broker.py
```

Em outros terminais:

```bash
cd python
python server/server.py --server-id py_server_1 --backend-endpoint tcp://localhost:5556
python client/client.py --username bot_client_1 --endpoint tcp://localhost:5555
```

### Java

```bash
cd java
mvn clean package
```

Exemplos:

```bash
java -jar target/chat-distribuido-java-1.0.0.jar --mode server --server-id java_server_1 --endpoint tcp://localhost:5556
java -jar target/chat-distribuido-java-1.0.0.jar --mode client --username java_bot_1 --endpoint tcp://localhost:5555
```

## Observacao sobre arquivos gerados

A classe Protobuf Java (`ChatProtocol`) e gerada durante o build Maven. Por isso, a pasta `java/target` nao precisa ser versionada para deploy, desde que o pipeline rode o build normalmente.

## Requisitos atendidos na Parte 1

- ZeroMQ em comunicacao distribuida
- Request-Reply
- Broker para multiplos servidores
- Serializacao binaria
- Timestamp em mensagens
- Persistencia por servidor
- Orquestracao com Docker Compose

## Autores

- Python: Pedro Satoru
- Java: Pedro Correia
