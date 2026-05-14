# Sistema de Chat Distribuido

Implementacao da Parte 3 do projeto de Sistemas Distribuidos com interoperabilidade entre Python e Java, incluindo:
- pub/sub em canais;
- relogio logico (Lamport) nas mensagens;
- sincronizacao de relogio fisico dos servidores via servico de referencia;
- heartbeat de disponibilidade dos servidores.

## Visao Geral

A arquitetura possui broker Req/Rep, proxy Pub/Sub e um servico de referencia para coordenacao de servidores.

Topologia em execução:

Topologia em execucao:

- 1 Broker Req-Rep (Python): gerencia login, listagem e criacao de canais (portas 5555/5556).
- 1 Proxy Pub/Sub (Python): gerencia distribuicao de mensagens por topico/canal (portas 5557/5558).
- 1 Servico de Referencia (Python): responde rank/list/heartbeat e fornece hora de referencia (porta 5559).
- Servidores (Python/Java): atuam como REPs para o broker, PUBs para o proxy e clientes REQ do servico de referencia.
- Clientes/Bots (Python/Java): atuam como REQs para o broker e SUBs para o proxy.

## Tecnologias e Decisoes

### Comunicação Pub/Sub
### Comunicacao Pub/Sub
- Proxy centralizado: proxy ZeroMQ (XSUB/XPUB) para desacoplar publicadores (servidores) e inscritos (clientes).
- Topicos: nomes de canais sao usados como topicos no ZeroMQ.

### Relogio Logico (Lamport)
- Toda mensagem de cliente para servidor inclui logical_clock.
- Antes de enviar, o processo incrementa seu contador logico.
- Ao receber, o processo atualiza com max(local, recebido) + 1.
- Campos logical_clock foram adicionados em ClientRequest, ServerResponse e ChatMessage.

### Sincronizacao de Relogio Fisico e Heartbeat
- Cada servidor solicita rank ao iniciar (acao rank no servico de referencia).
- A cada 10 mensagens de cliente processadas, servidor envia heartbeat.
- A resposta de heartbeat inclui reference_time_ms para ajuste de offset do relogio local.
- Servidores inativos sao removidos da lista de disponiveis pelo servico de referencia.

### Persistência
### Persistencia
O servidor persiste historico de mensagens e eventos:
- Python Server: arquivos JSON em python/data/serverX_data.json.
- Java Server: arquivos texto em java/data/serverX_messages.txt, java/data/serverX_logins.txt e java/data/serverX_channels.txt.

### Protocolo (Protobuf)
Contrato principal em python/proto/chat.proto e java/src/main/proto/chat.proto.

Mensagens principais:
- LoginRequest/LoginResponse
- ListChannelsRequest/ListChannelsResponse
- CreateChannelRequest/CreateChannelResponse
- PublishRequest/PublishResponse
- ChatMessage
- ClientRequest/ServerResponse
- ReferenceRequest/ReferenceResponse/ServerInfo

Campos relevantes da Parte 3:
- logical_clock em ClientRequest, ServerResponse e ChatMessage
- reference_time_ms em ReferenceResponse

## Funcionamento dos Bots

Fluxo padrao:
1. Verifica que existem pelo menos 5 canais.
2. Se inscreve em pelo menos 3 canais.
3. Publica 10 mensagens (intervalo de 1s).
4. Exibe logs das mensagens recebidas via SUB.
5. Atualiza relogio logico em envios e recebimentos.

## Como executar

Subir todo o ambiente:

```bash
docker compose up --build
```

Para subir em segundo plano:

```bash
docker compose up --build -d
```

Para acompanhar logs:

```bash
docker compose logs -f
```

Para encerrar:

```bash
docker compose down
```

## Como validar a Parte 3

Sinais esperados em logs:
- Servidores Java/Python com evento de rank recebido do servico de referencia.
- Heartbeat enviado a cada 10 mensagens de cliente.
- Campos lc=... aparecendo e crescendo monotonicamente.
- Publicacoes pub/sub entre clientes e servidores de linguagens diferentes.

Servicos chave no compose:
- broker
- python_proxy
- python_reference
- java_server_1 / java_server_2
- python_server_1 / python_server_2
- java_client_1 / java_client_2
- python_client_1 / python_client_2

## Estrutura do Projeto

```text
python/
  broker/
    broker.py (Req-Rep)
    proxy.py  (Pub-Sub)
  reference/reference.py (Servico de referencia)
  client/client.py
  server/server.py
  schemas/data_models.py (Persistencia)
  schemas/logical_clock.py
  proto/chat.proto

java/
  src/main/java/
    ChatClientBotMain.java
    ChatServerMain.java
    ReferenceServiceClient.java
    LogicalClock.java
    PersistenceStore.java (Persistencia)
  src/main/proto/chat.proto

docker-compose.yaml

## Documentacao da Entrega 3

Detalhamento tecnico das alteracoes:
- Docs/entrega3-java-python.md
```

## Autores

- Python: Pedro Satoru
- Java: Pedro Correia

---

## Parte 5: Consistencia e Replicacao

### Problema

Com o balanceamento de carga em round-robin do broker, cada servidor recebe e armazena apenas uma fração das mensagens trocadas. Se um servidor parar, parte do historico se perde. Se um cliente pedir o historico, recebe somente os dados do servidor que respondeu.

### Metodo escolhido: Replicacao Passiva via PUB/SUB existente

O sistema ja possui um proxy PUB/SUB (portas 5557/5558) que os servidores utilizam para publicar mensagens de chat aos clientes (SUBscribers).

**Ideia:** reutilizar esse mesmo canal PUB/SUB para que cada servidor tambem ASSINE (SUB) o proxy e, ao receber uma `ChatMessage`, armazene-a localmente caso ainda nao exista.

#### Fluxo de replicacao

```
Cliente → Broker (round-robin) → Servidor X
                                   ├── armazena localmente
                                   └── PUB → Proxy PUB/SUB
                                              ├── SUB → Clientes (comportamento existente)
                                              ├── SUB → Servidor Y → armazena copia [NOVO]
                                              └── SUB → Servidor Z → armazena copia [NOVO]
```

#### Como foi implementado

- Cada servidor cria um segundo socket SUB (`replication_sub_socket` em Python, `replicationSub` em Java) conectado ao proxy, inscrito em **todos os topicos** (prefixo vazio `""`).
- Uma thread dedicada (`_replication_listener` / `replication-listener`) fica escutando mensagens nesse socket.
- Ao receber uma `ChatMessage`, o servidor verifica se ja a possui (por chave `timestamp_ms|channel|text`) antes de armazenar — evitando duplicatas, inclusive das proprias publicacoes.
- O evento `REPL_STORE` e registrado no log sempre que uma mensagem e armazenada por replicacao.

#### Adaptacoes em relacao ao metodo teorico

A replicacao passiva classica pressupoe um primario que envia copias explicitamente aos backups. Aqui adaptamos para usar o canal PUB/SUB ja existente como mecanismo de difusao, o que evita a criacao de novos sockets ou protocolo. O resultado e equivalente: todos os servidores recebem todas as mensagens enquanto estao online (consistencia eventual). Mensagens publicadas enquanto um servidor esta offline nao sao recuperadas automaticamente ao voltar.

#### Deduplicacao

- **Python:** metodo `add_message_if_new()` em `ServerData` com conjunto `_seen_message_keys` (reconstruido a partir do JSON ao reiniciar).
- **Java:** metodo `appendPublishedMessageIfNew()` em `PersistenceStore` com `Set<String> seenMessageKeys` em memoria.

#### Arquivos alterados

| Arquivo | Alteracao |
|---|---|
| `python/schemas/data_models.py` | `add_message_if_new()` + `_seen_message_keys` |
| `python/server/server.py` | socket SUB de replicacao + thread `_replication_listener` |
| `java/src/main/java/PersistenceStore.java` | `appendPublishedMessageIfNew()` + `seenMessageKeys` |
| `java/src/main/java/ChatServerMain.java` | socket SUB de replicacao + thread `replication-listener` |

#### Validacao

Sinais esperados nos logs apos `docker compose up --build`:
- `[evt=SUB_REPL]` em todos os servidores na inicializacao.
- `[evt=REPL_STORE]` aparecendo nos servidores que *nao* processaram a requisicao original ao receber copias pelo proxy.
- Apos execucao, `python/data/server1_data.json` e `server2_data.json` devem conter as mesmas mensagens.
- `java/data/java_server_1_messages.txt` e `java_server_2_messages.txt` devem conter as mesmas linhas.

