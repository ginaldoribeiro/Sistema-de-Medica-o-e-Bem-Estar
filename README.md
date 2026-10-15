# MedRemind

App de gestão de medicações feito em **Python + Flet** a partir do protótipo do Stitch. Um único código
roda em **Android, iOS, web e desktop**.

![Telas do MedRemind](docs/telas.png)

Os dados ficam **no aparelho**, em SQLite, sem conta e sem nuvem, porque são dados de saúde (LGPD, art. 11).

## Como rodar

```bash
pip install -r requirements.txt

python main.py --demo          # janela desktop com dados de exemplo
python main.py --web --demo    # no navegador: http://localhost:8550
python main.py                 # começa vazio, com boas-vindas e consentimento
python -m pytest               # 28 testes
```

Gerar instaladores (exige Flutter SDK; veja a documentação do Flet):

```bash
flet build apk     # Android
flet build ipa     # iOS (macOS + Xcode)
flet build web     # site estático
```

## O que o app faz

| Tela | Funcionalidades |
|---|---|
| **Boas-vindas** | Carrossel de 3 passos, Pular / Começar |
| **Consentimento** | Termo LGPD com aceite obrigatório e estatísticas anônimas opcionais (o aceite fica registrado na auditoria) |
| **Bloqueio** | PIN de 4 a 6 dígitos com hash PBKDF2-SHA256 e bloqueio progressivo após 5 erros |
| **Início** | Saudação, meta diária (anel), doses restantes, dias seguidos, cartão da próxima dose (tomar, adiar, pular), alerta de estoque, atalhos e programação do dia |
| **Meus remédios** | Busca, filtros (ativos, estoque baixo, pausados, "se precisar"), barra de estoque, dose avulsa para remédios "conforme necessário" |
| **Adicionar / editar** | 5 formas, concentração, quantidade por dose, todo dia / dias fixos / se precisar, vários horários, duração contínua ou em dias, estoque com aviso, lembretes, pausar e excluir |
| **Histórico** | Semana navegável, adesão de 30 dias comparada ao mês anterior, barras por semana, registro detalhado (toque para corrigir) |
| **Estoque** | Previsão de quantos dias faltam, reposição, farmácia cadastrada e busca no mapa |
| **Hidratação** | Meta configurável, copo e garrafa, quantidade livre, desfazer |
| **Perfil** | Dados pessoais, contatos de emergência com botão de ligar, farmácia, preferências de notificação |
| **Assistente** | Agente com ferramentas: lista doses, diz a próxima, registra "tomei a aspirina", anota água, consulta estoque e resume a adesão |
| **SOS** | Ligar para o 192 (SAMU), contatos e ficha médica (tipo sanguíneo, alergias, condições, remédios em uso) |
| **Relatório médico** | Período de 7, 30 ou 90 dias; gera um CSV e uma página HTML para imprimir ou salvar em PDF |
| **Backup** | Exporta e restaura em JSON com verificação SHA-256; o PIN nunca vai no backup |
| **Auditoria** | Acessos, tentativas negadas e alterações |

Os lembretes são verificados a cada 30 s com o app aberto. Cada um traz Tomei / Adiar 10 min / Pular e
pode se repetir até você confirmar (alerta persistente).

## Arquitetura

```
medremind/
├── core/                  ← regras de negócio, sem dependência de interface
│   ├── models.py          dataclasses e enums (Medication, DoseLog, PlannedDose…)
│   ├── db.py              SQLite com migrações versionadas (PRAGMA user_version)
│   ├── repositories.py    única camada que conhece SQL
│   ├── container.py       injeção de dependências
│   ├── demo.py            dados de exemplo do protótipo
│   └── services/
│       ├── schedule.py    agenda, status das doses, adesão, sequência
│       ├── medications.py cadastro, validação, previsão de estoque
│       ├── assistant.py   agente: ferramentas + motor local + motor com LLM
│       ├── reminders.py   motor de lembretes
│       ├── security.py    PIN e bloqueio
│       ├── backup.py · reports.py · hydration.py · audit.py
├── ui/                    ← Flet
│   ├── theme.py           tokens de design (cores, fonte Plus Jakarta Sans)
│   ├── components.py      cartões, chips, botões, linhas…
│   ├── app.py             navegação, diálogos, ciclo de lembretes
│   └── views/             uma função por tela
api/server.py              ← API REST opcional (FastAPI), usa o mesmo núcleo
tests/                     ← pytest (relógio falso para testar horários)
```

- **O núcleo não conhece a interface.** O mesmo `Container` atende o app, a API e os testes.
- **O tempo é injetado.** Todo serviço recebe um `clock`, e os testes usam um `FakeClock` para simular
  horários e janelas de tolerância.
- **O status da dose é calculado, não guardado.** Só ações explícitas viram registro (tomado, pulado,
  adiado). "Agora", "perdido" e "agendado" saem do relógio:
  - "agora" vai de 30 min antes até 2 h depois do horário;
  - depois disso, sem registro, a dose conta como perdida.
- **O estoque é descontado uma única vez por dose.** Desfazer ou pular depois de tomar devolve a unidade.

## Assistente com IA

O assistente funciona de dois jeitos:

1. **Local (padrão).** Entende comandos em português por regras. Funciona offline e nada sai do aparelho.
2. **Com IA.** Defina `ANTHROPIC_API_KEY` (e, opcionalmente, `MEDREMIND_LLM_MODEL`). O `LLMAgent` usa a
   Messages API com *tool use*: o modelo escolhe as ferramentas, o app executa e devolve o resultado.
   Se a chamada falhar, o motor local assume.

Algumas regras valem nos dois modos:

- emergências ("dor no peito", "socorro") e pedidos de risco ("posso dobrar a dose?") são sempre tratados
  localmente: o assistente encaminha para o 192 ou para o médico;
- o assistente nunca recomenda nem altera doses.

Para criar uma ferramenta nova, registre um `Tool(nome, descrição, schema, handler)` em `AssistantTools`.
Os dois motores passam a usá-la.

## API REST (opcional)

```bash
MEDREMIND_API_TOKEN=troque-isto uvicorn api.server:app --port 8000
```

Endpoints (todos pedem `Authorization: Bearer <token>`, menos `/health`):

- `GET /medications` e `POST /medications`
- `GET /doses/today` e `POST /doses/take`
- `GET /adherence?days=30`
- `GET /stock`
- `GET /report.csv` e `GET /report.html`
- `POST /assistant`

Sem token configurado, a API recusa todas as chamadas.

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `MEDREMIND_DATA_DIR` | Pasta dos dados (padrão `~/.medremind`; nos builds móveis, a pasta do app) |
| `ANTHROPIC_API_KEY` / `MEDREMIND_LLM_MODEL` | Liga o assistente com IA |
| `MEDREMIND_API_TOKEN` | Token da API REST |
| `MEDREMIND_START_ROUTE` | Abre direto numa tela (desenvolvimento) |

## Limitações e próximos passos

- **Notificação com o app fechado.** No Android e no iOS isso exige agendamento nativo, por exemplo uma
  extensão Flet para `flutter_local_notifications`. Hoje os lembretes funcionam com o app aberto, e no
  desktop também como notificação do sistema (`plyer`).
- **Biometria.** A tela de acesso usa PIN. Digital ou rosto exigem uma extensão `local_auth`.
- **Voz.** O assistente recebe texto. Reconhecimento e síntese de voz podem ser adicionados por extensão.
- **Outras telas.** Smartwatch, Smart TV, carro e o painel do médico do protótipo podem consumir a API REST.

> O MedRemind organiza lembretes e registros. Ele não substitui orientação médica.
