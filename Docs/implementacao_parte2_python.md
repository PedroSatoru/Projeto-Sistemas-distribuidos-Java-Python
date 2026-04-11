# Relatório de Implementação: Parte 2 (Foco Python)

Este documento detalha o que foi implementado na **Parte 2** do trabalho de Sistemas Distribuídos na stack Python. A entrega contempla a adoção de canais de comunicação com modelo Publisher/Subscriber (Produtor/Consumidor), com intermédio através de um Proxy do ZeroMQ e bots que assinam, postam e mensuram o desempenho do envio.

## 1. Contrato Protobuf (`chat.proto`)
Para comportar a troca de mensagens na Parte 2 sem quebrar a comunicação `ROUTER-DEALER` (Parte 1), o contrato `chat.proto` foi expandido em ambos os diretórios (Python e Java). Foram incluídas as três novas estruturas:
- `PublishRequest`: Usada pelos clientes para solicitar a publicação de uma string de log em um canal (trafegando juntamente do seu Timestamp de disparo em base `ms`).
- `PublishResponse`: Retorno padrão dos Servidores acusando recebimento e efetivo processamento (sucesso ou erro).
- `ChatMessage`: Quando o evento de Publish é aprovado no roteador, o Servidor envelopa o texto nesta mensagem estruturada. Além do Timestamp de Envio nativo, o payload trafegado reflete as marcas do próprio `username` que efetuou a submissão e a chave String de `channel_name`.

## 2. Padrão Arquitetural Inserido: PUB/SUB
A lógica do envio contínuo da Parte 2 para múltiplos ouvintes desvinculou-se das premissas binárias do Request/Reply original. Um terceiro elemento vital (O Proxy) precisou ser construído:

* **O novo componente Proxy Pub/Sub (`python/broker/proxy.py`):**
  Opera escutando produtores de carga por meio de um bind `zmq.XSUB` na sua porta frontal (`tcp://*:5557`) e retransmitindo pacotes cegamente por tramas contínuas aos consumidores inscritos por meio de um `zmq.XPUB` na traseira (`tcp://*:5558`). 

* **O Servidor como único Publisher Exclusivo:**
  Todas a publicações devem provir essencialmente dos clientes. Logo, eles submetem via Router Request, e o Server cuida do processo logando no disco o dado e utilizando um socket assíncrono conectado como `PUB` apontado pra porta 5557 do Proxy. O Servidor utiliza as etiquetas de inscrição (topics stringing) compondo _multipart frames_ no envio para rotear pelo nome do canal.

* **O Cliente (Bot) como Subscriber:**
  Dentro do loop principal enraizado em `client.py`, foi inserida uma Thread multitarefa não bloqueante e transparente ao fluxo rotineiro. Ela é inicializada pela diretiva ZeroMQ alocada na porta 5558 e absorve através das amarrações `zmq.SUB` os canais interessados na assinatura. A cada milissegundo as saídas decodificam o Diff (Latência).

## 3. Lógica Comportamental do Bot (Requisitos Atendidos)
Conforme exigido pelo escopo do projeto, o Bot client agora engaja nas rotinas pré-moldadas e autônomas:
1. Ao realizar login com êxito, ele inspeciona os canais públicos via a `ListChannelsMessage`.
2. Caso o ecossistema encontre restrição e detecte **menos que 5 canais** disponíveis, engatilham requests ativas na API de `CreateChannelMessage` forçando strings hexadecimais automáticas até nivelar aos exatos 5 canais.
3. Posteriormente o Bot renova a chamada, coleta a lista populada e procede vinculando via socket options estritos (`.setsockopt_string(zmq.SUBSCRIBE, ...)`) em **três canais**.
4. Inicia iterativamente o *Loop Eterno* pinçando nos índices randômicos remetendo cascatas de **10 mensagens** unidas à **1 segundo** de delay entre si contabilizando exaustivamente no buffer receptor a resposta final.

## 4. Particionamento e Retornos Distribuídos
A infraestrutura não abarca um motor de DB atrelado nas sessões de estado, e portanto os micro-serviços Python carregam matrizes de dados desacoplados independentes (_State Without Locking Shared_), espelhados pelo comportamento nos logs da Parte 1, provando o tráfego e contenções:
Ao submeter Request num canal aleatório a balança do DEALER encaminha para os servidores A ou B que detêm suas listas desiguais do storage do Python (`serverX_data.json`). Quando o Broker manda para instâncias onde a sala pedida para publicar diverge ele estritamente lança `ERROR_RESPONSE` - sem derreter instâncias e de forma estável, onde os bots se encarregam das abstrações contínuas subsequentes.

## 5. Docker Compose Exclusivo 
Para fins de modularidade entre o time acadêmico, modelou-se um compose a mais no caminho do root intitulado `docker-compose-python.yaml`.  Expurgando os blocos da linguagem Java do colega, permite testar o circuito Python via:
`docker compose -f docker-compose-python.yaml up --build`
