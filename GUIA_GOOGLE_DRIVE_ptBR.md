# Guia: enviar dados das estações pelo Google Drive (sincronização diária)

**Para quem é este guia.** Ele tem duas partes bem separadas:

- **PARTE 1 — Configuração (feita UMA vez, pela Jéssica ou por quem cuida do site).** É a parte mais técnica: criar um "robô" do Google que tem permissão de ler uma pasta do Drive, e contar ao GitHub como usá‑lo. Leva ~30–40 minutos, só uma vez na vida.
- **PARTE 2 — Uso do dia a dia (feito pela pessoa que envia os dados).** É simplíssimo: *arrastar o arquivo para uma pasta do Google Drive*. Nada de código, nada de GitHub. Essa pessoa só precisa ler a Parte 2.

---

## Como funciona (a versão de 1 minuto)

Existe uma pasta compartilhada no Google Drive. Um "robô" (uma automação do GitHub) olha essa pasta **todo dia de manhã**, **copia** qualquer arquivo novo que estiver lá para dentro do projeto do site e atualiza o painel automaticamente. **O arquivo permanece na pasta do Drive** — o robô só copia, nunca move nem apaga (o acesso dele é **somente leitura**). Ele anota o que já trouxe, então não processa o mesmo arquivo duas vezes; se você **atualizar** um arquivo (novo conteúdo), ele é lido de novo.

```
  Colega arrasta o arquivo
  para a pasta do Google Drive ──►  robô diário do GitHub  ──►  dados atualizados  ──►  painel no ar
                                     (todo dia de manhã)          no projeto
```

Duas garantias importantes: (1) é **incremental** — o robô só acrescenta o arquivo novo, nunca refaz tudo; enviar o mesmo arquivo duas vezes não causa problema; (2) é **de graça** — roda no GitHub (Actions + Pages), sem servidor para pagar.

---

# PARTE 1 — Configuração (uma única vez)

> Você vai criar uma **"conta de serviço"** do Google. Pense nela como um *usuário‑robô*: um e‑mail especial que não é uma pessoa, serve só para o programa acessar a pasta. Você dá a esse robô permissão na pasta do Drive, e entrega a "senha" dele (um arquivo `.json`) ao GitHub, guardada em segredo.

## 1.1 Criar o projeto e ligar a API do Google Drive

1. Abra <https://console.cloud.google.com> e entre com a sua conta Google.
2. No topo da tela, clique no **seletor de projeto** (ao lado do logotipo "Google Cloud") → **Novo projeto** (*New project*). Dê um nome, por exemplo `joinville-meteo`, e clique em **Criar**. Espere alguns segundos e selecione esse projeto no mesmo seletor.
3. No menu (☰, canto superior esquerdo) vá em **APIs e serviços → Biblioteca** (*APIs & Services → Library*).
4. Na busca, digite **Google Drive API**, clique no resultado e clique em **Ativar** (*Enable*).

## 1.2 Criar a conta de serviço (o "usuário‑robô")

1. Menu ☰ → **APIs e serviços → Credenciais** (*Credentials*).
2. Clique em **Criar credenciais** (*Create credentials*) → **Conta de serviço** (*Service account*).
3. Dê um nome, por exemplo `sincroniza-drive`, e clique em **Criar e continuar** (*Create and continue*).
4. Na etapa de **permissões (papel/role)**, você pode **deixar em branco** e clicar em **Continuar** e depois **Concluir** (*Done*). *(Por quê: o acesso não vem de um "papel" no projeto — vem de você compartilhar a pasta com o e‑mail dele, no passo 1.4. Se a tela exigir um papel, escolha "Leitor/Viewer" — tanto faz.)*
5. Você voltará à lista de contas de serviço. **Copie o e‑mail** da conta que apareceu — ele tem a cara de `sincroniza-drive@joinville-meteo.iam.gserviceaccount.com`. Guarde esse e‑mail; você vai usá‑lo já já.

## 1.3 Baixar a "senha" da conta de serviço (arquivo JSON)

1. Ainda em **Credenciais**, clique no nome da conta de serviço que você criou.
2. Abra a aba **Chaves** (*Keys*).
3. Clique em **Adicionar chave** (*Add key*) → **Criar nova chave** (*Create new key*) → escolha o formato **JSON** → **Criar**.
4. Um arquivo `.json` será **baixado automaticamente** para o seu computador. **Esse arquivo é uma senha — trate com cuidado** (veja §Segurança no final). Não envie por e‑mail nem coloque em pasta pública.

> Se o botão de criar chave estiver bloqueado, a sua organização pode ter uma política que proíbe isso. Nesse caso, faça a Parte 1 com uma **conta Google pessoal** (um projeto pessoal no Google Cloud), onde essa restrição não existe.

## 1.4 Criar a pasta no Drive e compartilhar com o robô

1. Abra <https://drive.google.com> e crie uma pasta, por exemplo **`Joinville_meteo_incoming`**.
2. Clique com o botão direito na pasta → **Compartilhar** (*Share*).
3. No campo de pessoas, **cole o e‑mail da conta de serviço** (o do passo 1.2, `...gserviceaccount.com`), defina a permissão como **Leitor** (*Viewer*) e confirme/enviar. *(O robô só **lê e copia** os arquivos — acesso somente leitura —, então Leitor basta. "Editor" também funciona, mas não é necessário.)*
4. Abra a pasta e olhe o endereço (URL) no navegador. Ele é assim:
   `https://drive.google.com/drive/folders/`**`1A2b3C4d5E6...`** — **copie a parte final** (depois de `folders/`). Isso é o **ID da pasta**. Guarde.

## 1.5 Guardar os segredos no GitHub

No GitHub, abra o repositório do projeto → **Settings → Secrets and variables → Actions**.

1. Na aba **Secrets**, clique em **New repository secret** e crie **dois** segredos:
   - Nome: `GDRIVE_SA_JSON` — Valor: **abra o arquivo `.json`** que você baixou (em um editor de texto), selecione **todo** o conteúdo e cole aqui. (Cole o conteúdo inteiro, das chaves `{` até `}`.)
   - Nome: `GDRIVE_FOLDER_ID` — Valor: **cole o ID da pasta** (o `1A2b3C4d5E6...` do passo 1.4).
2. Ainda nessa tela, clique na aba **Variables** → **New repository variable**:
   - Nome: `DRIVE_SYNC_ENABLED` — Valor: `true`.

> Esses "segredos" ficam **criptografados** no GitHub. Ninguém consegue lê‑los depois de salvos (nem você) — só as automações usam. Se precisar trocar, você substitui o segredo.

## 1.6 Deixar a sincronização DIÁRIA

De fábrica o projeto sincroniza **uma vez por semana** (segundas‑feiras). Para virar **diário**, é preciso mudar **duas** linhas de agendamento (nos arquivos das automações). Você pode fazer isso pelo próprio site do GitHub (editar o arquivo → *Commit*), ou me pedir que eu deixo pronto.

- Arquivo **`.github/workflows/sync-drive.yml`** — troque a linha do agendamento para:
  ```yaml
  schedule:
    - cron: "30 8 * * *"     # todo dia 08:30 UTC (~05:30 em Joinville)
  ```
- Arquivo **`.github/workflows/update-data.yml`** — troque para rodar 30 min depois, todo dia:
  ```yaml
  schedule:
    - cron: "0 9 * * *"      # todo dia 09:00 UTC (~06:00 em Joinville)
  ```

**Por que duas linhas:** o robô do Drive (`sync-drive`) leva os arquivos para dentro do projeto, e um segundo robô (`update-data`) é quem realmente processa esses arquivos e atualiza o painel. Por um detalhe técnico do GitHub, o segundo não é "acordado" automaticamente pelo primeiro — por isso ele roda 30 minutos depois, pegando o que acabou de chegar. Deixando os dois diários, o ciclo inteiro passa a ser diário. *(O painel em si publica sozinho a cada 6 horas, então o dado novo aparece no ar no máximo poucas horas depois.)*

## 1.7 Testar agora (sem esperar o horário)

1. Coloque **um arquivo de teste** na pasta do Drive.
2. No GitHub → aba **Actions** → clique em **"Sync Google Drive → incoming"** → botão **Run workflow** (executar agora).
3. Em ~1 minuto, a automação termina (✓ verde). **O arquivo continua na pasta do Drive** (o robô só copiou) — no log da execução dá para ver "new files copied: N". Logo depois, a automação **"Update datasets"** roda e processa. Deu certo se ambas ficarem com o ✓ verde.

---

# PARTE 2 — Uso do dia a dia (para quem envia os dados)

**É só isto:** abra a pasta compartilhada **`Joinville_meteo_incoming`** no seu Google Drive e **arraste para dentro dela o arquivo exportado da estação**. Pronto. Não precisa renomear, não precisa escolher nada, não precisa de GitHub.

- Uma vez por dia, de manhã, o sistema pega o que estiver lá e atualiza o painel sozinho.
- O arquivo **permanece na pasta** — o robô só faz uma cópia; não apaga nem move nada. Você pode organizar/remover seus arquivos quando quiser; o robô lembra o que já processou e não repete.
- Pode colocar vários arquivos de uma vez.

### Que arquivos enviar

Envie os arquivos **como saem da estação/planilha**, sem renomear — o sistema reconhece cada um pelo conteúdo:

| Origem | Cara do arquivo |
|---|---|
| Dataloggers Campbell (estações da Defesa Civil) | `*_5.dat`, `*_HR.dat`, `*_DIARIA.dat` (formato TOA5) |
| Estação UDESC/CCT (console Ecowitt) | `AAAAMM*.CSV` (ex.: `202607A.CSV`) |
| Pluviômetros | CSV com `pluvi` / `gauge` / `chuva` no nome |
| Histórico em planilha | `*.xlsx` |

Se um arquivo não for reconhecido, o sistema simplesmente o ignora (nada quebra) e registra que pulou aquele arquivo.

---

## Como saber que deu certo

- No GitHub → aba **Actions**: você verá **"Sync Google Drive → incoming"** e depois **"Update datasets"** rodarem (✓ verde = concluído). Clicando na execução, o log mostra **quantas linhas novas** cada estação ganhou.
- Poucas horas depois (no máximo), o painel no ar já mostra os dados novos. Para publicar na hora, dá para abrir **Actions → "Deploy dashboard to Pages" → Run workflow**.

## Problemas comuns

- **"Não aconteceu nada no painel."** (O arquivo continuar na pasta é normal — o robô só copia.) Verifique se a variável `DRIVE_SYNC_ENABLED` está como `true` (§1.5) e se a pasta foi compartilhada com o e‑mail do robô (Leitor basta, §1.4). Rode a sincronização à mão (§1.7); no log, "new files copied: 0" quando não há arquivo novo é esperado.
- **A automação falhou (✗ vermelho) logo no início.** Quase sempre é o `GDRIVE_SA_JSON` colado incompleto — reabra o arquivo `.json` e cole o conteúdo **inteiro** de novo.
- **"O botão de criar chave JSON está bloqueado."** Política da organização; use um projeto em conta Google pessoal (§1.3).
- **O dado apareceu no painel mas não bate.** Aí não é envio — é dado; me avise que a gente investiga o controle de qualidade.

## Segurança (importante)

- O arquivo **`.json` é como uma senha**. Não mande por e‑mail nem WhatsApp, não suba em pasta pública. O único lugar onde ele deve ser colado é no **GitHub Secrets** (§1.5). Depois de colar lá, pode apagar o `.json` do computador.
- A conta de serviço **só enxerga a pasta que você compartilhou** — nada mais do seu Drive. Isso limita bastante o risco.
- Se desconfiar que a chave vazou: no Google Cloud → conta de serviço → **Chaves** → apague a chave antiga e **crie uma nova** (§1.3), depois atualize o segredo `GDRIVE_SA_JSON` no GitHub. A antiga deixa de valer na hora.
- Quem só usa a Parte 2 (envia dados) **não precisa** de nada disso: essa pessoa nunca vê a chave nem o GitHub — só a pasta do Drive.

## Glossário rápido

- **Conta de serviço:** um "usuário‑robô" do Google, usado por programas (não é uma pessoa).
- **Chave JSON:** o arquivo que funciona como senha dessa conta‑robô.
- **ID da pasta:** o código no fim do endereço da pasta do Drive.
- **Secret (segredo) do GitHub:** um valor sensível guardado criptografado, que só as automações usam.
- **Action / workflow:** uma automação que roda no GitHub (aqui: sincronizar o Drive, processar os dados, publicar o site).

---

*Projeto gerido pelo Laboratório de Ciência das Águas (LaCiA) — PPGEC, UDESC/CCT Joinville. Fonte dos dados: SEPROT / Prefeitura de Joinville.*
