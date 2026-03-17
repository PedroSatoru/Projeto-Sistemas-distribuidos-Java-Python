# Sistema de Chat Distribuído - Parte 1: Login e Criação de Canais

## Introdução

Este é o código Python para a Parte 1 do projeto de Sistema de Chat Distribuído. Implementa funcionalidades básicas de autenticação e gerenciamento de canais usando ZeroMQ para comunicação distribuída.


## Arquitetura e Escolhas

### 1. Comunicação: ZeroMQ (Obrigatório)

- **Padrão utilizado:** REQUEST-REPLY (REQ-REP)
- **Por que:** Ideal para comunicação síncrona cliente-servidor com garantia de entrega
- **Configuração:** 
  - Servidor aguarda em `tcp://*:5555` e `tcp://*:5556` (2 servidores)
  - Clientes conectam via `tcp://hostname:porta`
  - Timeout de 5000ms para requisições

### 2. Serialização: MessagePack

- **Formato:** Binário, mais compacto que JSON/XML
- **Por que:** 
  - Leve e eficiente
  - Suporta tipos complexos
  - Amplamente compatível (funcionará com cliente Java)
- **Inclusão de Timestamp:** ✅ Obrigatório - todas as mensagens contêm timestamp do envio

**Estrutura de Mensagem:**
```python
{
    "type": "LOGIN",  # Tipo da mensagem
    "timestamp": 1710705600.123,  # Timestamp UNIX (obrigatório)
    "payload": {  # Dados específicos da mensagem
        "username": "bot_user"
    }
}
```

### 3. Persistência: JSON

- **Arquivo:** `server_data.json` (um por servidor)
- **Dados armazenados:**
  - Lista de usuários logados
  - Lista de canais criados
  - Histórico de logins com timestamps
- **Localização:** `/data/` no container

**Exemplo de arquivo:**
```json
{
  "users": ["bot_client_1", "bot_client_2"],
  "channels": ["general", "random", "announcements"],
  "login_history": [
    {
      "username": "bot_client_1",
      "timestamp": 1710705600.123,
      "datetime": "2024-03-17T12:00:00.123456"
    }
  ]
}
```

### 4. Validação de Nomes

- **Regra:** Alfanuméricos, underscores (`_`) e hífens (`-`)
- **Case-Insensitive:** SIM (canais "General" e "general" são iguais)
- **Autenticação:** Apenas usuários em `users.txt` podem fazer login
- **Erros tratados:**
  - Nome com formato inválido (caracteres especiais, espaços, vazio)
  - Usuário não registrado em `users.txt`
  - Usuário já logado
  - Canal já existente

## Estrutura do Projeto

```
python/
├── server/
│   └── server.py           # Implementação do servidor
├── client/
│   └── client.py           # Implementação do cliente (bot)
├── schemas/
│   ├── __init__.py
│   ├── messages.py         # Definição das mensagens MessagePack
│   └── data_models.py      # Modelos de persistência JSON
├── data/                   # Diretório de volumes (criado em runtime)
├── users.txt               # Usuários permitidos (um por linha)
├── Dockerfile              # Imagem Docker
└── requirements.txt        # Dependências Python

docker-compose.yaml         # Orquestração (raiz do projeto)
README.md                   # Este arquivo
```

## Autenticação de Usuários

Para aumentar a segurança do sistema (mesmo que não usemos senhas), **apenas usuários pré-cadastrados podem fazer login**.

### Arquivo de Usuários Permitidos

**Arquivo:** `python/users.txt`

Contém um usuário por linha:
```
bot_client_1
bot_client_2
bot_client_3
bot_client_4
alice
bob
charlie
diana
```

### Fluxo de Login

1. Cliente envia username
2. Servidor valida **formato** (alfanumérico + underscore + hífen)
3. Servidor valida se username está em `users.txt`
4. Se tudo OK, usuário faz login e é persistido
5. Se falhar em qualquer validação, retorna erro descritivo

### Erros de Login

- "Invalid username format..." → Nome contém caracteres inválidos
- "User not registered..." → Nome não está em `users.txt`
- "User already logged in." → Username já logado em outra conexão

## Dependências

```
pyzmq==25.1.2          # Binding Python para ZeroMQ
msgpack==1.0.7         # Serialização MessagePack
```

## Mensagens Implementadas

### 1. LOGIN

**Requisição (Cliente → Servidor):**
```json
{
    "type": "LOGIN",
    "timestamp": 1710705600.123,
    "payload": {"username": "bot_user"}
}
```

**Resposta (Servidor → Cliente):**
- Sucesso: `{"type": "LOGIN_RESPONSE", "payload": {"success": true}}`
- Erro: `{"type": "LOGIN_RESPONSE", "payload": {"success": false, "error": "User already logged in."}}`

---

### 2. LIST_CHANNELS

**Requisição:**
```json
{
    "type": "LIST_CHANNELS",
    "timestamp": 1710705600.123,
    "payload": {}
}
```

**Resposta:**
```json
{
    "type": "LIST_CHANNELS_RESPONSE",
    "timestamp": 1710705600.450,
    "payload": {"channels": ["general", "random", "tech"]}
}
```

---

### 3. CREATE_CHANNEL

**Requisição:**
```json
{
    "type": "CREATE_CHANNEL",
    "timestamp": 1710705600.123,
    "payload": {"channel_name": "announcements"}
}
```

**Resposta:**
- Sucesso: `{"type": "CREATE_CHANNEL_RESPONSE", "payload": {"success": true}}`
- Erro: `{"type": "CREATE_CHANNEL_RESPONSE", "payload": {"success": false, "error": "Invalid channel name."}}`

## Como Executar

### Opção 1: Docker Compose (Recomendado)

```bash
cd <raiz-do-projeto>
docker compose up
```

Isso vai:
- Compilar a imagem Docker do Python
- Iniciar 2 servidores Python (portas 5555 e 5556)
- Iniciar 4 clientes bot automáticos (2 por servidor)
- Exibir logs de todas as operações em tempo real

Para parar:
```bash
docker compose down
```

### Opção 2: Execução Local

**Terminal 1 - Servidor 1:**
```bash
cd python
pip install -r requirements.txt
python server/server.py --port 5555
```

**Terminal 2 - Servidor 2:**
```bash
cd python
python server/server.py --port 5556
```

**Terminal 3 - Cliente 1:**
```bash
cd python
python client/client.py --host localhost --port 5555 --username bot1 --channels "general,random"
```

**Terminal 4 - Cliente 2:**
```bash
cd python
python client/client.py --host localhost --port 5556 --username bot2 --channels "tech,music"
```

## Fluxo de Execução

1. **Cliente conecta ao servidor** via ZeroMQ
2. **Cliente realiza LOGIN** com seu nome de usuário
3. **Servidor valida** e persiste no JSON
4. **Cliente lista canais** disponíveis
5. **Cliente cria novos canais** (um por um)
6. **Cliente lista canais novamente** para verificar
7. Todos os dados são **persistidos em JSON** no servidor

## Saída Esperada (Exemplo)

```
# BOT STARTING - 2024-03-17T12:00:00.123456
[CLIENT] Initialized. Username: bot_client_1
[CLIENT] Connecting to python_server_1:5555

============================================================
[CLIENT] STEP 1: LOGIN
============================================================
[SENDING] Type: LOGIN, Timestamp: 2024-03-17T12:00:00.123456
[SENDING] Payload: {'username': 'bot_client_1'}
[RECEIVED] Type: LOGIN_RESPONSE
[RECEIVED] Payload: {'success': True}
[SUCCESS] Login successful!

============================================================
[CLIENT] STEP 2: LIST CHANNELS
============================================================
[SENDING] Type: LIST_CHANNELS, Timestamp: 2024-03-17T12:00:01.234567
[RECEIVED] Type: LIST_CHANNELS_RESPONSE
[RECEIVED] Payload: {'channels': []}
[SUCCESS] Received 0 channel(s): []

============================================================
[CLIENT] STEP 3: CREATE CHANNELS
============================================================
[SENDING] Type: CREATE_CHANNEL, Timestamp: 2024-03-17T12:00:02.345678
[SENDING] Payload: {'channel_name': 'general'}
[RECEIVED] Type: CREATE_CHANNEL_RESPONSE
[RECEIVED] Payload: {'success': True}

# BOT COMPLETED - 2024-03-17T12:00:05.678901
```

## Servidor - Logs de Operações

```
[SERVER] Started on port 5555
[SERVER] Data file: server_data.json
[SERVER] Waiting for messages...

[LOGIN SUCCESS] User 'bot_client_1' logged in at 2024-03-17T12:00:00.123456
[LIST CHANNELS] Returning 0 channels: []
[CREATE CHANNEL SUCCESS] Channel 'general' created at 2024-03-17T12:00:02.345678
```

## Tratamento de Erros (Grosseiros)

- ❌ Nome com formato inválido → "Invalid username format. Only alphanumeric, underscore, and hyphen allowed."
- ❌ Usuário não registrado → "User not registered. Check users.txt file."
- ❌ Usuário já logado → "User already logged in."
- ❌ Canal já existe → "Channel already exists."
- ❌ Nome de canal inválido → "Invalid channel name. Only alphanumeric characters allowed."
- ⏱️ Timeout de resposta → "Request timeout - no response from server"

## Observações Importantes

1. **Cada servidor tem seus próprios dados** - `server1_data.json` e `server2_data.json` são independentes
2. **Caso-insensitive:** Canais "General" e "general" são tratados como o mesmo
3. **Bots não possuem interação manual** - Tudo é automático via docker-compose
4. **Timestamps incluídos em TODAS as mensagens** - Conforme obrigatório
5. **Servidores persistem dados em disco** - Sobrevivem a reinicializações

## Próximas Partes do Projeto

- **Parte 2:** Publicação e recebimento de mensagens
- **Parte 3:** Replicação entre servidores
- **Parte 4:** Tolerância a falhas
- **Parte 5:** Otimizações e melhorias

## Integração com Java

Quando a dupla tiver o código Java pronto:
1. Adicionar serviços Java no `docker-compose.yaml`
2. Usar os mesmos message schemas (MessagePack)
3. Conectar via rede bridge do Docker Compose
4. Manter compatibilidade de timestamps

## Autores

- **Python:** [Seu Nome]
- **Java:** [Nome da dupla]

## Licença

MIT - Projeto acadêmico
