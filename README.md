# Sistema de Chat Distribuído - Parte 2

Implementação da Parte 2 do projeto de Sistemas Distribuídos com interoperabilidade entre Python e Java, introduzindo o padrão Publisher-Subscriber para publicação em canais.

## Visão Geral

A arquitetura foi expandida para incluir um proxy Pub/Sub dedicado, permitindo que os usuários se inscrevam em canais e recebam mensagens em tempo real.

Topologia em execução:

- **1 Broker Req-Rep (Python)**: Gerencia login, listagem e criação de canais (Portas 5555/5556).
- **1 Proxy Pub/Sub (Python)**: Gerencia a distribuição de mensagens nos canais (Portas 5557/5558).
- **Servidores (Python/Java)**: Atuam como REPs para o broker e como PUBs para o proxy.
- **Clientes/Bots (Python/Java)**: Atuam como REQs para o broker e como SUBs para o proxy.

## Tecnologias e Decisões

### Comunicação Pub/Sub
- **Proxy Centralizado**: Optamos por um proxy ZeroMQ (XSUB/XPUB) centralizado para desacoplar totalmente os publicadores (servidores) dos inscritos (clientes). Isso facilita a escalabilidade e a interoperabilidade.
- **Tópicos**: Os nomes dos canais são usados como tópicos no ZeroMQ. O filtragem é feita pelo proxy e pelos sockets SUB dos clientes.

### Persistência
O servidor agora persiste o histórico de mensagens e eventos:
- **Python Server**: Utiliza arquivos JSON (`python/data/serverX_data.json`) para persistir canais, histórico de logins e todas as mensagens publicadas. O JSON foi escolhido pela facilidade de manipulação e legibilidade em Python.
- **Java Server**: Utiliza arquivos de texto plano (`java/data/serverX_messages.txt`, etc.) com campos delimitados por `|`. Esta escolha visa simplicidade e performance em Java, facilitando o parse manual se necessário.

### Protocolo (Protobuf)
O contrato foi atualizado para incluir:
- `PublishRequest`: Para solicitação de publicação via REQ-REP.
- `ChatMessage`: Estrutura da mensagem enviada via PUB-SUB.

## Funcionamento dos Bots

Seguindo o padrão estabelecido:
1. **Verificação de Canais**: O bot garante que existam pelo menos 5 canais no sistema.
2. **Inscrição**: O bot se inscreve em pelo menos 3 canais aleatórios.
3. **Loop de Publicação**: Escolhe um canal aleatório e publica 10 mensagens (intervalo de 1s).
4. **Logs**: Exibe no console cada mensagem recebida via SUB, contendo Canal, Mensagem, Timestamp de Envio e Timestamp de Recebimento.

## Como executar

Subir todo o ambiente:

```bash
docker compose up --build
```

## Estrutura do Projeto

```text
python/
  broker/
    broker.py (Req-Rep)
    proxy.py  (Pub-Sub)
  client/client.py
  server/server.py
  schemas/data_models.py (Persistência)
  proto/chat.proto

java/
  src/main/java/
    ChatClientBotMain.java
    ChatServerMain.java
    PersistenceStore.java (Persistência)
  src/main/proto/chat.proto

docker-compose.yaml
```

## Autores

- Python: Pedro Satoru
- Java: Pedro Correia
