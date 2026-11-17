# Controle de Chaves — Modelo de Dados

Modelo de dados (PostgreSQL) do módulo de **controle de chaves**: quem retirou qual chave de qual sala, quando e quem recebeu a devolução. O módulo roda no mesmo projeto Django do chatbot, no app `chaves`, e as telas ficam no painel em `/painel/chaves/`.

| Arquivo | O que é |
|---|---|
| `chaves/models.py` | Fonte da verdade (modelos Django) |
| `chaves/migrations/0001_initial.py` | Migration que cria as tabelas |
| `docs/diagrama-er-chaves.drawio` | Diagrama ER editável no draw.io |
| `docs/diagrama-er-chaves.png` / `.svg` | Diagrama exportado (imagem) |
| `docs/schema-chaves.sql` | DDL PostgreSQL gerado com `python manage.py sqlmigrate chaves 0001` |
| `docs/gerar_diagrama_chaves.py` | Script que gera o `.drawio` e confere o traçado |

---

## 1. Checklist da tarefa

| Item do checklist | Onde está |
|---|---|
| Identificar as entidades Usuário, Sala, Chave, Empréstimo e Movimentação | Seção 2. Tabelas `chaves_usuario`, `chaves_sala`, `chaves_chave`, `chaves_emprestimo` e `chaves_movimentacao` |
| Definir os campos principais de cada entidade | Seção 3 (campo, tipo PostgreSQL, obrigatório, chave) |
| Desenhar os relacionamentos no draw.io | `docs/diagrama-er-chaves.drawio` (+ `.png`/`.svg`), resumidos na seção 4 |
| Definir chaves primárias, estrangeiras e campos obrigatórios | Seção 3 (colunas PK/FK/NN) e seção 5 (regras no banco) |
| Enviar o diagrama para revisão com o back-end | Os modelos Django já estão implementados e migrados (`chaves/models.py`). O back-end pode revisar diagrama e código lado a lado |

---

## 2. Entidades

| Entidade | Tabela | Para que serve |
|---|---|---|
| **Usuário** | `chaves_usuario` | Pessoa que retira chaves: aluno, professor, servidor ou visitante. Não tem login no sistema. |
| **Sala** | `chaves_sala` | Sala física que tem fechadura: sala de aula, laboratório, auditório ou administrativa. |
| **Chave** | `chaves_chave` | Chave física de uma sala. Uma sala pode ter várias cópias, cada uma com o próprio código. |
| **Empréstimo** | `chaves_emprestimo` | Uma retirada de chave: quem pegou, quando, até quando deve devolver, e quando devolveu. |
| **Movimentação** | `chaves_movimentacao` | Histórico (auditoria) de tudo que acontece com uma chave: cadastro, retirada, devolução, manutenção, perda e liberação. Nunca é editada. |
| *Funcionário* | `core_usuario` | Já existe no projeto (login do painel). Aparece como o operador que registrou cada empréstimo, devolução e movimentação. |

> **Usuário × Funcionário:** são duas coisas diferentes. O *usuário* é quem pega a chave no balcão. O *funcionário* é quem está logado no sistema e registra a operação. Separar os dois permite cadastrar alunos e visitantes sem criar login para eles.

---

## 3. Campos

Legenda: **PK** chave primária · **FK** chave estrangeira · **UQ** valor único · **NN** obrigatório (NOT NULL) · **CK** tem regra CHECK. `timestamptz` = `timestamp with time zone`.

### Usuário (`chaves_usuario`)

| Campo | Tipo | NN | Chave | Observação |
|---|---|---|---|---|
| id | bigint | sim | PK | identidade gerada pelo banco |
| nome | varchar(120) | sim | | |
| matricula | varchar(30) | sim | UQ | matrícula ou documento; não repete |
| tipo | varchar(20) | sim | CK | `aluno`, `professor`, `servidor`, `visitante` |
| email | varchar(254) | sim* | | pode ficar vazio (`''`) |
| telefone | varchar(30) | sim* | | pode ficar vazio (`''`) |
| ativo | boolean | sim | | usuário inativo não retira chave |
| criado_em | timestamptz | sim | | |

### Sala (`chaves_sala`)

| Campo | Tipo | NN | Chave | Observação |
|---|---|---|---|---|
| id | bigint | sim | PK | |
| codigo | varchar(20) | sim | UQ | ex.: `B-204` |
| nome | varchar(100) | sim | | ex.: Laboratório de Informática 1 |
| bloco | varchar(20) | sim* | | pode ficar vazio |
| andar | smallint | não | | |
| tipo | varchar(20) | sim | | `aula`, `laboratorio`, `auditorio`, `administrativa` |
| capacidade | integer | não | CK | vazia ou maior que zero |
| ativa | boolean | sim | | sala inativa não empresta chave |

### Chave (`chaves_chave`)

| Campo | Tipo | NN | Chave | Observação |
|---|---|---|---|---|
| id | bigint | sim | PK | |
| sala_id | bigint | sim | FK → `chaves_sala.id` | PROTECT |
| codigo | varchar(30) | sim | UQ | ex.: `B-204-01` |
| descricao | varchar(150) | sim* | | ex.: cópia reserva |
| status | varchar(20) | sim | CK | `disponivel`, `emprestada`, `manutencao`, `perdida` |
| criado_em | timestamptz | sim | | |

### Empréstimo (`chaves_emprestimo`)

| Campo | Tipo | NN | Chave | Observação |
|---|---|---|---|---|
| id | bigint | sim | PK | |
| chave_id | bigint | sim | FK → `chaves_chave.id` | UNIQUE parcial: um empréstimo aberto por chave |
| usuario_id | bigint | sim | FK → `chaves_usuario.id` | quem retirou |
| registrado_por_id | bigint | sim | FK → `core_usuario.id` | funcionário que registrou a retirada |
| retirada_em | timestamptz | sim | CK | |
| devolucao_prevista | timestamptz | sim | CK | tem que ser depois da retirada |
| devolvido_em | timestamptz | não | CK | vazio = empréstimo em aberto |
| recebido_por_id | bigint | não | FK → `core_usuario.id`, CK | funcionário que recebeu a devolução |
| observacao | varchar(255) | sim* | | |

A situação **atrasado** não é guardada: é calculada (`devolvido_em IS NULL AND devolucao_prevista < agora`). Assim ela nunca fica desatualizada.

### Movimentação (`chaves_movimentacao`)

| Campo | Tipo | NN | Chave | Observação |
|---|---|---|---|---|
| id | bigint | sim | PK | |
| chave_id | bigint | sim | FK → `chaves_chave.id` | |
| emprestimo_id | bigint | não | FK → `chaves_emprestimo.id`, CK | obrigatório em retirada/devolução |
| usuario_id | bigint | não | FK → `chaves_usuario.id`, CK | obrigatório em retirada/devolução |
| operador_id | bigint | sim | FK → `core_usuario.id` | funcionário que registrou |
| tipo | varchar(20) | sim | CK | `cadastro`, `retirada`, `devolucao`, `manutencao`, `perda`, `liberacao` |
| data_hora | timestamptz | sim | | |
| observacao | varchar(255) | sim* | | |

\* Campos de texto opcionais seguem o padrão do Django: são `NOT NULL` no banco e guardam `''` quando não preenchidos.

---

## 4. Relacionamentos

| Pai (1) | Filho (N) | FK | Cardinalidade | Leitura |
|---|---|---|---|---|
| Sala | Chave | `chave.sala_id` | 1 : 0..N | uma sala **possui** várias chaves (cópias) |
| Chave | Empréstimo | `emprestimo.chave_id` | 1 : 0..N | uma chave **é emprestada** muitas vezes, mas só uma em aberto |
| Usuário | Empréstimo | `emprestimo.usuario_id` | 1 : 0..N | um usuário **retira** várias chaves |
| Chave | Movimentação | `movimentacao.chave_id` | 1 : 0..N | cada chave **gera** seu histórico |
| Empréstimo | Movimentação | `movimentacao.emprestimo_id` | 0..1 : 0..N | um empréstimo **origina** a retirada e a devolução |
| Usuário | Movimentação | `movimentacao.usuario_id` | 0..1 : 0..N | quem retirou ou devolveu |
| Funcionário | Empréstimo | `emprestimo.registrado_por_id` | 1 : 0..N | funcionário **registra** a retirada |
| Funcionário | Empréstimo | `emprestimo.recebido_por_id` | 0..1 : 0..N | funcionário **recebe** a devolução |
| Funcionário | Movimentação | `movimentacao.operador_id` | 1 : 0..N | funcionário **opera** cada movimentação |

Na prática, Empréstimo é a tabela associativa entre **Usuário** e **Chave** (N:N ao longo do tempo).

Todas as FKs usam **ON DELETE PROTECT**: não dá para apagar uma sala que tem chaves, nem uma chave ou um usuário que já tem empréstimos. Para tirar de uso, marca-se como inativo, perdido ou em manutenção, e o histórico continua preservado.

---

## 5. Regras de integridade no banco

Ficam no próprio PostgreSQL (constraints), então valem mesmo se alguém gravar direto no banco.

| Constraint | Tabela | Regra | Por quê |
|---|---|---|---|
| `chaves_um_emprestimo_aberto_por_chave` | empréstimo | `UNIQUE (chave_id) WHERE devolvido_em IS NULL` | a mesma chave não pode estar emprestada para duas pessoas ao mesmo tempo |
| `chaves_emprestimo_prevista_apos_retirada` | empréstimo | `devolucao_prevista > retirada_em` | prazo de devolução coerente |
| `chaves_emprestimo_devolucao_apos_retirada` | empréstimo | `devolvido_em IS NULL OR devolvido_em >= retirada_em` | não existe devolução antes da retirada |
| `chaves_emprestimo_devolucao_completa` | empréstimo | `devolvido_em` e `recebido_por_id` preenchidos juntos, ou ambos vazios | toda devolução registra quem recebeu a chave |
| `chaves_movimentacao_emprestimo_obrigatorio` | movimentação | tipo `retirada`/`devolucao` exige `emprestimo_id` e `usuario_id` | o histórico sempre aponta o empréstimo e a pessoa |
| `chaves_movimentacao_tipo_valido` | movimentação | tipo dentro da lista | sem valores inválidos |
| `chaves_chave_status_valido` | chave | status dentro da lista | sem valores inválidos |
| `chaves_usuario_tipo_valido` | usuário | tipo dentro da lista | sem valores inválidos |
| `chaves_sala_capacidade_positiva` | sala | `capacidade IS NULL OR capacidade > 0` | capacidade zero ou negativa não faz sentido |
| UNIQUE | sala, chave, usuário | `codigo` da sala, `codigo` da chave, `matricula` | sem cadastro duplicado |

Índice extra: `chaves_emp_aberto_idx (devolvido_em, devolucao_prevista)` deixa rápidas as consultas de "em aberto" e "atrasados".

Além do banco, a regra de negócio (`chaves/services.py`) trava a linha da chave (`SELECT … FOR UPDATE`) ao emprestar e mantém `chave.status` sincronizado com o empréstimo. Cada operação grava a sua Movimentação na mesma transação.

---

## 6. Fluxo

1. **Cadastro:** sala → chave(s) da sala (gera a movimentação `cadastro`) → usuários.
2. **Empréstimo:** o funcionário escolhe uma chave *disponível* e o usuário, e informa a devolução prevista. Isso cria o Empréstimo, muda a chave para `emprestada` e grava a movimentação `retirada`.
3. **Devolução:** o funcionário registra a devolução. O sistema preenche `devolvido_em` e `recebido_por`, a chave volta para `disponivel` e grava a movimentação `devolucao` (com "(com atraso)" se passou do prazo).
4. **Outros estados:** uma chave que não está emprestada pode ir para `manutencao` ou `perdida` e depois ser liberada. Cada mudança gera a sua movimentação.
