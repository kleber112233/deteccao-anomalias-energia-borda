# Preparo do Raspberry Pi 5 para a etapa 2

Escrito em 21/11/2026. Versões conferidas nesse dia (site da Raspberry Pi e PyPI).

**A placa é um Raspberry Pi 5** (o plano e o texto antigo do artigo falavam em Pi 4; ver "O que muda por ser um Pi 5" no fim).

## Estado em 22/11/2026: Pi pronto (vale mais que o resto do documento)

- **Cartão novo** (identificação `manfid 0x0000c9`, `oemid 0x4d60`, nome `MSSD0`), aprovado: `dpkg --verify` sem nenhum
  arquivo alterado logo depois de gravar e depois da instalação.
- **Sistema:** Raspberry Pi OS (Legacy, 64-bit) Lite, Debian 12, Python 3.11.2, kernel com página de 16 kB.
  Placa: Raspberry Pi 5 Model B Rev 1.0, **4 GB** de memória.
- **Endereço atual: `192.168.0.57`** (`ssh kleber_tcc@192.168.0.57`). O roteador trocou o endereço ao regravar;
  reservar um IP fixo para o Pi no roteador.
- **Feito:** fuso `America/Sao_Paulo`; `apt install mosquitto mosquitto-clients python3-venv git htop` (sem `full-upgrade`);
  Mosquitto liberado para a rede (`/etc/mosquitto/conf.d/tcc.conf`: `listener 1883`, `allow_anonymous true`), testado do
  PC com `Test-NetConnection 192.168.0.57 -Port 1883`; pasta copiada para `~/tcc-pi`; venv com `requirements-pi.txt`
  instalado sem erro; `requirements-pi.lock.txt` gerado no Pi.
- **`conferir_pi.py` no Pi: "Tudo certo".** ONNX Runtime 1.32.0 e scikit-learn 1.9.1 funcionam com a página de 16 kB
  (não foi preciso o `kernel8.img`). Isolation Forest de teste: 6,9 ms por amostra (scikit-learn puro, 100 árvores;
  só um teste de fumaça, não é resultado do TCC).
- **Temperatura: 63,4 °C em repouso, sem dissipador nem ventoinha.** Sob carga contínua o Pi 5 passa de 80 °C e reduz a
  velocidade; para o E3/E4 será preciso refrigeração (mini ventoinha 5 V nos pinos 4 e 6, de preferência com dissipador).
- **Ponta a ponta testado (22/11/2026):** simulador no Windows (Python 3.11, venv em `simulador/.venv`, 32 testes
  aprovados) com `python -m casasim tempo-real --cenario perfil1 --mqtt 192.168.0.57 --velocidade 60`; no Pi, o
  `conferir_pi.py --segundos 20` recebeu 160 mensagens (8/s) dos 5 canais do perfil 1, nenhuma fora do contrato e nenhum
  campo de gabarito. **O preparo do Pi está concluído.**

## Atualização de 21/11/2026 à noite: o que os testes mudaram

O que está neste bloco vale mais do que o resto do documento onde houver diferença.

- **Sistema em uso: Raspberry Pi OS (Legacy, 64-bit) Lite**, Debian 12 "bookworm", **Python 3.11.2** (a mesma versão do
  simulador). Todos os pacotes do `requirements-pi.txt` têm versão pronta para Python 3.11 em aarch64 (conferido).
- **CONCLUSÃO DE 21/11 (fim da noite): o cartão microSD está com defeito e precisa ser trocado.** Ele troca o conteúdo de
  arquivos por um padrão fixo de lixo (bytes `88 16 03 27 91 26 89 26`, repetidos), e isso aconteceu nas duas versões do sistema:
  - versão nova (Debian 13 "trixie", kernel 6.18), 1ª gravação: depois de `apt full-upgrade` e reboot, o Pi não voltou à rede;
  - versão nova, 2ª gravação: depois de gravar um arquivo pequeno em `/boot/firmware` e reiniciar, o LED piscou 7 vezes
    ("Kernel image not found"); o `chkdsk` no Windows mostrou um setor da lista de arquivos sobrescrito com esse lixo e
    42 MB em 7 arquivos perdidos;
  - versão Legacy (Debian 12), 3ª gravação: passou em dois reboots, mas o `apt install` falhou com
    `dpkg: error: too-long line or missing newline in '/var/lib/dpkg/arch'`; o arquivo tem os 12 bytes de tamanho certos e
    o mesmo lixo no lugar de `arm64\narmhf\n`. Nenhum pacote chegou a ser instalado.
  O cartão identifica-se como `manfid 0x000000`, `oemid 0x0000`, nome `SMI`, data 03/2023, 29,8 GiB, modo "high speed":
  é genérico, sem código de fabricante. A fonte está inocentada (`throttled=0x0`). Não foi testado se o defeito poderia
  ser do leitor de cartão do Pi; um cartão novo ou a partida por USB tiram essa dúvida.
- **Para continuar:** um microSD original (SanDisk, Samsung ou Kingston, 32 GB, classe A1 ou A2, de loja confiável) ou
  dar partida por um pendrive ou SSD USB (o Pi 5 inicia por USB quando não há cartão no slot; grava-se pelo Imager do
  mesmo jeito). Com a mídia nova, repetir o passo a passo a partir do passo 1. A versão nova do sistema não ficou
  condenada: o que ela sofreu foi o defeito do cartão. Manter a Legacy é a escolha simples, por já estar conferida e
  ter o Python 3.11 do simulador.
- **Fonte aprovada:** `vcgencmd get_throttled` deu `0x0`.
- **Acesso pelo IP, não pelo nome:** `ssh kleber_tcc@192.168.0.67`. O nome `pi-tcc.local` parou de resolver no Windows
  deste PC. Onde o documento usa `pi-tcc.local`, troque por `192.168.0.67` (inclusive no `--mqtt` do simulador).
  Vale reservar esse IP no roteador. Para achar o Pi se o IP mudar, no PowerShell:

      1..254 | % { $ip="192.168.0.$_"; $c=New-Object Net.Sockets.TcpClient; try { if ($c.ConnectAsync($ip,22).Wait(300) -and $c.Connected) { "SSH aberto em $ip" } } catch {}; $c.Close() }

- **Cabo de rede testado está com defeito** (sobe a 100 Mbps e cai um segundo depois, em ciclo). Para o E3/E4 será preciso outro cabo.
- **`apt full-upgrade`:** com um cartão bom, pode ser feito normalmente.
- **Fuso:** a gravação da Legacy não aplicou o fuso; ajustar com `sudo timedatectl set-timezone America/Sao_Paulo`.
- `diag-rede.sh` e `diag-rede.service` (nesta pasta) são uma ferramenta de diagnóstico que grava o estado da rede em
  `/boot/firmware/diag-rede.txt` a cada partida. Não está instalada no sistema atual; usar só se o Pi voltar a sumir da rede.
- Códigos de piscada do LED: https://www.raspberrypi.com/documentation/computers/configuration.html (7 piscadas = kernel não encontrado).


O Pi faz três coisas neste projeto: recebe a telemetria da casa (MQTT), roda os modelos (inferência) e
responde (alerta, Telegram, comando de desligar). **Ele não treina modelos e não roda o simulador**; isso
fica no notebook. Tudo o que está aqui foi escolhido para o Pi fazer essas três coisas com o mínimo de
programas rodando por trás, porque os experimentos E3/E4 medem quantos canais o Pi aguenta em tempo real, e
qualquer programa extra consumindo CPU entra na medida como ruído.

## O que instalar e por quê

| Camada | Escolha | Motivo |
| --- | --- | --- |
| Sistema | **Raspberry Pi OS Lite, 64 bits** (Debian 13 "trixie", versão de 06/10/2026) | 64 bits é obrigatório: scikit-learn, ONNX Runtime e LiteRT só publicam pacote pronto para ARM de 64 bits (aarch64). Lite (sem área de trabalho) porque o Pi vai ficar sem monitor e a interface gráfica gasta memória e CPU que entrariam na medida de capacidade. É o sistema oficial, o que facilita descrever e reproduzir no artigo. |
| Python | **3.13 do próprio sistema**, em ambiente virtual (`venv`) | Não precisa instalar outro Python: todos os pacotes abaixo têm versão pronta para 3.13 em aarch64 (conferido). O simulador continua no notebook em 3.11; os dois só conversam por MQTT/JSON, então as versões não precisam ser iguais. |
| Broker MQTT | **Mosquitto**, no próprio Pi | É o broker que Tasmota, Zigbee2MQTT e Shelly usam na prática. Com ele no Pi, a casa simulada e um medidor de verdade publicam no mesmo lugar, do mesmo jeito (é a promessa do contrato MQTT). É leve (poucos MB de memória). |
| Inferência | **ONNX Runtime** como runtime único | Os quatro modelos (IF, OCSVM, AE, LSTM-AE) podem ser exportados para `.onnx`. Um runtime só deixa a comparação de latência justa e elimina o problema de versão do pickle do scikit-learn entre notebook e Pi. Detalhes na seção "Runtime de inferência". |
| Modelos clássicos | **scikit-learn** (mesma versão do notebook) | Referência: serve para conferir que o `.onnx` dá o mesmo score e para medir, no Pi, o ganho de exportar. |
| Carga do Pi | **psutil** + `vcgencmd` (já vem no sistema) | A cascata ajusta o limiar τ pela carga do Pi; psutil dá CPU e memória por processo, `vcgencmd` dá temperatura e se houve limitação por calor ou subtensão. |
| Dados | **pandas + pyarrow** | Para ler os datasets congelados (Parquet) nas medições E1/E2 feitas no próprio Pi. |
| Histórico de alertas | **SQLite** (já vem no Python) | Guarda alertas e medições sem instalar banco de dados. |
| Telegram | **httpx** chamando a API do bot | A API é uma chamada HTTPS; não precisa de biblioteca própria. |
| Código | **git** | Desenvolve no notebook, dá `git pull` no Pi. Resolve também a pendência do repositório. |

### O que não instalar

- **Home Assistant, Node-RED, InfluxDB, Grafana:** fariam parte do trabalho por você (a banca pediu programação) e
  ocupam memória e CPU o tempo todo, o que contamina a medida de capacidade. O painel já existe no simulador
  e recebe os alertas por `casa/sistema/alertas`.
- **Docker:** uma camada a mais para explicar e medir, sem ganho aqui.
- **TensorFlow ou PyTorch completos no Pi:** servem para treinar. O treino fica no notebook; o Pi só precisa do runtime.
- **Área de trabalho, VNC:** o acesso é por SSH.

## Runtime de inferência: por que ONNX Runtime

Testado em 21/11/2026 (Python 3.13, scikit-learn 1.9.1, skl2onnx 1.20.0, onnxruntime 1.32.0, num computador x86):

- Isolation Forest e OCSVM convertidos com `skl2onnx` deram o mesmo score do scikit-learn (diferença máxima de
  1,6e-07 e 5,5e-06) e ficaram mais rápidos por amostra. Os tempos foram medidos em x86 e **não valem para o Pi**;
  a medida que interessa é a do E1/E2.
- Um LSTM autoencoder (duas camadas LSTM de 32, janela de 60) rodou no ONNX Runtime e aceitou quantização
  dinâmica para int8 (arquivo de 54 kB para 17 kB). Esse modelo foi montado direto em ONNX; a exportação a partir do
  PyTorch (`torch.onnx.export`) ainda precisa ser feita no notebook.

Alternativa: **LiteRT** (`ai-edge-litert`), o sucessor do TensorFlow Lite. O pacote `tflite-runtime`, citado no texto já
entregue do artigo, não tem mais versão para aarch64 com Python 3.11 ou 3.13 no PyPI; quem ocupa o lugar é o
`ai-edge-litert` (2.4.0, com pacote para aarch64). Ele serve só para AE e LSTM-AE, então IF e OCSVM ficariam em outro
runtime, e a conversão de LSTM para esse formato costuma dar mais trabalho. Como o pacote é pequeno, dá para instalar
os dois e incluir uma tabela comparando os runtimes no Pi, se você quiser esse resultado a mais.

**Consequência para o artigo (etapa 3):** o trecho da seção 3 que fala em "tflite-runtime" e ".tflite com quantização
int8" precisa ser reescrito conforme o runtime escolhido.

## Antes de começar: o hardware

- **Refrigeração:** o Pi 5 esquenta mais que o Pi 4. Use o cooler ativo (dissipador com ventoinha, encaixa na própria
  placa). Sem ele, sob carga contínua, o Pi passa de 80 °C e reduz a velocidade sozinho; se isso acontecer no meio do
  E3/E4, o resultado mede o calor e não o método.
- **Fonte:** a oficial do Pi 5 (USB-C, 27 W, 5 V e 5 A). Com uma fonte de 5 V e 3 A ele liga e funciona sem periféricos,
  mas é o limite; subtensão também faz o Pi reduzir a velocidade, e o `conferir_pi.py` mostra se isso aconteceu.
- **Cartão:** microSD de 32 GB ou mais, classe A1/A2.
- **Rede:** cabo de rede para os experimentos de capacidade. No Wi-Fi, a perda e o atraso da rede podem limitar o
  resultado antes da CPU. Para desenvolver e para a demonstração, Wi-Fi serve.

## Passo a passo

### 1. Gravar o cartão (no notebook)

Telas conforme a documentação oficial do Imager em 21/11/2026.

1. Baixe o **Raspberry Pi Imager** em https://www.raspberrypi.com/software/, instale e abra. Ponha o microSD no leitor.
2. Aba **Device:** Raspberry Pi 5.
3. Aba **OS:** role a lista até *Raspberry Pi OS (other)*, entre nele e escolha **Raspberry Pi OS (Legacy, 64-bit) Lite**
   (ver a atualização no topo; a "Lite (64-bit)" sem Legacy é a versão nova, que corrompeu o cartão).
   As primeiras opções da lista (64-bit, 32-bit, Legacy) são todas com área de trabalho; não é nenhuma delas.
4. Aba **Storage:** o microSD (confira pelo tamanho; deixe "Exclude system drives" marcado).
5. Aba **Customisation**, uma subaba por vez:
   - **Hostname:** `pi-tcc`
   - **Localisation:** capital Brasília; confira fuso `America/Sao_Paulo` e teclado `br`
   - **User:** usuário em minúsculas (os exemplos usam `kleber_tcc`) e uma senha que você vá lembrar
   - **Wi-Fi:** a rede de casa e a senha (o Imager costuma preencher com a rede em que o PC está)
   - **Remote Access:** ligue **Enable SSH**, com autenticação por senha
   - **Raspberry Pi Connect:** deixe desligado
6. Aba **Writing:** confira o resumo e grave. Leva alguns minutos.
7. Ponha o cartão no Pi e ligue na fonte. A primeira partida leva uns dois ou três minutos.

### 2. Entrar no Pi (do PowerShell do notebook)

    ssh kleber_tcc@pi-tcc.local

Se `pi-tcc.local` não resolver, veja o IP do Pi na lista de aparelhos do roteador e use `ssh kleber_tcc@<ip>`.
Vale reservar esse IP no roteador (reserva de DHCP), para ele não mudar.

#### Sem monitor: como controlar e ver o Pi pelo PC

O Pi não precisa de monitor, teclado nem mouse em nenhum momento. O que torna isso possível é a personalização do
passo 1 (nome, usuário, Wi-Fi e SSH ativado): ele já liga pela primeira vez conectado à rede e aceitando acesso remoto.
Daí em diante há três jeitos de usar, todos a partir do PC:

- **Terminal (SSH):** o comando acima. É por onde se instala e se roda tudo. O Windows 10/11 já traz o `ssh`.
- **VS Code com a extensão "Remote - SSH"** (da Microsoft): abre as pastas do Pi no VS Code do PC, com editor, explorador de
  arquivos e terminal, como se fosse uma pasta local. É a forma mais confortável de "ver" o Pi. Feche antes de medir.
- **Navegador:** o painel do simulador roda no PC e mostra os alertas que o Pi publica. O que o Pi vier a ter de página
  própria abre em `http://pi-tcc.local:<porta>`.

Para não digitar senha toda vez (e para o VS Code conectar direto), crie uma chave no PowerShell do PC, uma única vez:

    ssh-keygen -t ed25519
    type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh kleber_tcc@pi-tcc.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

E crie o arquivo `C:\Users\klebe\.ssh\config` com:

    Host pi-tcc
        HostName pi-tcc.local
        User kleber_tcc

A partir daí, `ssh pi-tcc` entra direto, e no VS Code basta F1 → "Remote-SSH: Connect to Host" → `pi-tcc`.

Se o Pi não aparecer na rede depois de ligar:
- espere uns três minutos na primeira partida;
- confira se o PC está na mesma rede (rede de convidados costuma isolar os aparelhos);
- nome ou senha do Wi-Fi errados na personalização: regrave o cartão, ou ligue o Pi no roteador por cabo, que funciona sem configurar nada;
- para desligar com segurança, sempre `sudo poweroff` antes de tirar da tomada (protege o cartão).

### 3. Atualizar e instalar os programas do sistema (no Pi)

    sudo timedatectl set-timezone America/Sao_Paulo
    sudo apt update
    sudo apt install -y mosquitto mosquitto-clients python3-venv git htop
    sudo reboot

Depois de reiniciar, entre de novo e confira:

    uname -m              # tem que dar aarch64
    python3 --version     # 3.11.x na Legacy
    vcgencmd measure_temp
    vcgencmd get_throttled   # tem que dar throttled=0x0

### 4. Abrir o Mosquitto para a rede de casa

A partir da versão 2, o Mosquitto só aceita conexão da própria máquina. Para o notebook publicar nele:

    printf 'listener 1883\nallow_anonymous true\n' | sudo tee /etc/mosquitto/conf.d/tcc.conf
    sudo systemctl restart mosquitto
    systemctl is-active mosquitto      # tem que dar active

Isso deixa o broker sem senha, o que é aceitável numa rede doméstica de teste. O simulador ainda não manda usuário e
senha; quando isso for acrescentado nele, troque `allow_anonymous true` por um arquivo de senhas. No artigo, vale dizer
que uma instalação real usaria autenticação.

### 5. Primeiro teste de ponta a ponta

No Pi, deixe escutando:

    mosquitto_sub -t 'casa/#' -v

No notebook, na pasta `simulador` com o ambiente ativado:

    python -m casasim tempo-real --cenario perfil1 --mqtt pi-tcc.local --velocidade 60

As mensagens de telemetria devem aparecer no terminal do Pi. Se não aparecerem, troque `pi-tcc.local` pelo IP.

### 6. Copiar esta pasta para o Pi e criar o ambiente Python

Do PowerShell do notebook (enquanto o repositório não existe):

    scp -r C:\Users\klebe\Desktop\faculdade\TCC\pi kleber_tcc@pi-tcc.local:~/tcc-pi

No Pi:

    cd ~/tcc-pi
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements-pi.txt
    pip freeze > requirements-pi.lock.txt

### 7. Conferir tudo

Com o simulador publicando (passo 5):

    python conferir_pi.py --segundos 20

O script mostra sistema, temperatura, pacotes, um teste de inferência e o que chegou pelo MQTT, e termina com
"Tudo certo" ou com a lista de pendências. Guarde a saída: é o registro do ambiente para a seção de métodos.

## Para os experimentos (não precisa agora)

- **Governador da CPU:** o sistema varia a frequência do processador conforme a carga, o que deixa a latência irregular.
  Antes de cada medição:

      echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

  Volta ao normal quando o Pi reinicia. Anote no artigo.
- **Antes e depois de cada rodada:** `vcgencmd get_throttled` e `vcgencmd measure_temp`. Se não der `0x0`, descarte a rodada.
- **Nada mais rodando:** feche o VS Code remoto e outras sessões durante a medição.
- **Relógio:** a latência de detecção do E5 sai do registro ao vivo, gravado no notebook (hora da falha injetada e hora
  do alerta recebido, as duas no relógio do notebook), então não depende de os dois relógios estarem iguais. Mesmo assim,
  mantenha o sincronismo automático do Pi ligado, porque o `ts` dos alertas usa o relógio dele.
- **Serviço:** quando o detector existir, ele vira um serviço do `systemd` para subir sozinho ao ligar o Pi
  (bom para a demonstração à banca).

## Editar código no Pi

Duas formas; as duas funcionam:

- **git** (recomendado): edita no notebook, `git push`; no Pi, `git pull`. Os datasets (864 MB) ficam fora do
  repositório; quando o Pi precisar de uma partição de teste, copie com `scp`.
- **VS Code com a extensão Remote - SSH:** edita os arquivos do Pi direto do notebook. É cômodo, mas o servidor do
  VS Code ocupa algumas centenas de MB de memória no Pi; feche antes de medir.

## O que muda por ser um Pi 5

- **Nada na instalação:** o mesmo sistema, os mesmos pacotes e os mesmos comandos.
- **Página de memória de 16 kB:** o Pi 5 usa por padrão um kernel com páginas de 16 kB (`getconf PAGESIZE` dá 16384), e
  alguns pacotes compilados já tiveram problema com isso. Não testei os pacotes daqui num Pi 5. Se algum falhar ao
  importar (o `conferir_pi.py` acusa), a saída é acrescentar `kernel=kernel8.img` em `/boot/firmware/config.txt` e
  reiniciar, o que volta para páginas de 4 kB.
- **Experimentos de capacidade (E3/E4):** o processador do Pi 5 é bem mais rápido que o do Pi 4, então o ponto de
  saturação fica mais alto. A rampa do gerador de carga talvez precise ir além do previsto, e o próprio notebook
  (~3.000 mensagens/s medidas sem broker) pode virar o limite antes do Pi. Verificar no primeiro ensaio.
- **Texto do projeto:** o plano, o README do simulador, o LEIAME do catálogo e as seções 1 a 3 do artigo falam em
  Raspberry Pi 4. As latências e comparações com a literatura citadas para o Pi 4 precisam ser revistas na etapa 3.
