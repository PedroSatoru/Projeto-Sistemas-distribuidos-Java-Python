# Implementacao Parte 2 - Pub/Sub Java

## Objetivo
Implementar o padrao Publisher-Subscriber no modulo Java, mantendo:
- broker unico (REQ/REP)
- proxy unico (PUB/SUB)
- interoperabilidade completa entre clientes/servidores Python e Java

A implementacao foi feita seguindo o comportamento da referencia Python e os cenarios descritos em `Aulas/projeto/parte2.md`.

## Arquitetura Final

### REQ/REP (inalterado)
- Clientes Java e Python enviam `ClientRequest` para o broker (`tcp://broker:5555`)
- Servidores Java e Python respondem via broker backend (`tcp://broker:5556`)

### PUB/SUB (parte 2)
- Proxy unico Python:
  - XSUB: `tcp://*:5557` (entrada de publicadores)
  - XPUB: `tcp://*:5558` (saida para subscribers)
- Servidores Java e Python publicam no proxy em `tcp://python_proxy:5557`
- Clientes Java e Python assinam topicos no proxy em `tcp://python_proxy:5558`

## Alteracoes no Contrato Protobuf

### Campo adicionado em PublishRequest
Foi adicionado `username` para preservar o autor real da publicacao no `ChatMessage`:

```proto
message PublishRequest {
  int64 timestamp_ms = 1;
  string channel_name = 2;
  string message_text = 3;
  string username = 4;
}
```

Arquivos atualizados:
- `java/src/main/proto/chat.proto`
- `python/proto/chat.proto`
- gerado automaticamente em Java: `java/src/main/java/proto/ChatProtocol.java`

## Alteracoes no Java

### 1) Servico de negocio (`ChatService`)
Arquivo: `java/src/main/java/ChatService.java`

Implementado:
- tratamento de `PUBLISH_REQUEST`
- validacoes de publish:
  - nome de canal valido
  - canal existente
  - mensagem nao vazia
  - username valido quando fornecido
- montagem de `PublishResponse` com timestamp
- criacao de `ChatMessage` para envio via PUB/SUB
- persistencia de publicacoes no disco
- disponibilizacao do evento de publicacao para o servidor via `consumeLastPublication()`

### 2) Servidor Java (`ChatServerMain`)
Arquivo: `java/src/main/java/ChatServerMain.java`

Implementado:
- novo socket PUB conectado ao proxy unico
- novo argumento de configuracao:
  - `--pub-endpoint` (default: `tcp://python_proxy:5557`)
- apos processar publish com sucesso:
  - envia multipart `[topic(channel), payload(ChatMessage)]`
- persistencia agora inclui arquivo de mensagens por servidor:
  - `${serverId}_messages.txt`

### 3) Persistencia (`PersistenceStore`)
Arquivo: `java/src/main/java/PersistenceStore.java`

Implementado:
- novo arquivo de armazenamento de publicacoes (`messagesFile`)
- novo metodo `appendPublishedMessage(timestamp, username, channel, message)`
- formato de linha:
  - `timestamp|username|channel|message`

### 4) Codec (`ProtocolCodec`)
Arquivo: `java/src/main/java/ProtocolCodec.java`

Implementado:
- parse de `ChatMessage` vindo do SUB
- serializacao de `ChatMessage` para envio PUB

### 5) Cliente Bot Java (`ChatClientBotMain`)
Arquivo: `java/src/main/java/ChatClientBotMain.java`

Implementado:
- socket SUB para proxy unico
- novo argumento de configuracao:
  - `--sub-endpoint` (default: `tcp://python_proxy:5558`)
- listener de subscriber em thread daemon
- desserializacao de `ChatMessage` recebido do proxy
- exibicao em tela dos 4 campos exigidos na Parte 2:
  - canal
  - mensagem
  - timestamp de envio
  - timestamp de recebimento
- fluxo do bot conforme enunciado:
  1. login
  2. garantir minimo de 5 canais
  3. inscrever aleatoriamente ate 3 canais
  4. publicar no maximo 10 mensagens totais por execucao:
     - escolhe canal aleatorio
     - envia mensagem com intervalo de 1 segundo
- `PublishRequest` agora envia `username` real do bot

## Alteracoes no Python para Interoperabilidade
Mesmo com foco em Java, foram feitos ajustes minimos no Python para manter consistencia do contrato e interoperabilidade cruzada.

### Arquivos alterados
- `python/schemas/messages.py`
  - serializa e desserializa `username` em `PublishRequest`
- `python/client/client.py`
  - envia `username` no `PublishRequestMessage`
- `python/server/server.py`
  - usa `username` do request no `ChatMessage` publicado (fallback: `server`)

## Padrao unificado de logs (Python e Java)

Os logs foram padronizados para um formato unico e mais limpo:

`[ts=...][lang=...][role=...][id=...][lvl=...][evt=...] mensagem`

Componentes cobertos:
- cliente Python
- servidor Python
- broker Python
- proxy Python
- cliente Java
- servidor Java

## Alteracoes no Docker Compose
Arquivo: `docker-compose.yaml`

Atualizado para garantir proxy unico para Java:
- `java_server_1` e `java_server_2`:
  - adicionados `--pub-endpoint tcp://python_proxy:5557`
  - `depends_on` inclui `python_proxy`
- `java_client_1` e `java_client_2`:
  - adicionados `--sub-endpoint tcp://python_proxy:5558`
  - `depends_on` inclui `python_proxy`

Resultado:
- um unico broker para REQ/REP
- um unico proxy para PUB/SUB
- clientes e servidores Java/Python compartilhando os mesmos canais/topicos

## Validacao dos Cenarios da Parte 2
Cenarios cobertos pela implementacao:
- proxy PUB/SUB separado do broker (porta 5557/5558)
- inscricao em canais no cliente
- multiplas inscricoes por conexao
- exibicao de canal, mensagem, timestamp envio e timestamp recebimento
- publicacao via REQ no servidor e fan-out via PUB/SUB
- resposta de status de publicacao ao cliente
- persistencia das publicacoes no servidor
- fluxo padronizado de bot (5 canais, 3 inscricoes, limite de 10 publicacoes totais)

## Comandos de verificacao sugeridos

### Subir ambiente completo
```bash
docker compose -f docker-compose.yaml up --build
```

### Evidencia esperada nos logs
- servidor Java conectando em `tcp://python_proxy:5557`
- cliente Java conectando em `tcp://python_proxy:5558`
- logs `RECV_SUB` no cliente com os 4 campos obrigatorios
- arquivos `java/data/java_server_*_messages.txt` sendo atualizados
