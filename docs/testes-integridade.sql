-- Prova das regras de integridade direto no PostgreSQL.
-- Cada comando abaixo TENTA gravar um dado inválido e o banco recusa (ERROR).
-- Tudo roda dentro de uma transação desfeita no final (ROLLBACK): nada é alterado.
-- Rodar:  psql chatbot_atendimento -f docs/testes-integridade.sql
-- (precisa do banco populado: python manage.py popular_demo --conversas)

BEGIN;
SAVEPOINT a;
-- 1) Mesmo cliente do Telegram cadastrado duas vezes -> core_contato_telegram_chat_id_key
INSERT INTO core_contato (canal, nome, telegram_chat_id, telegram_username, email, telefone, criado_em, ultimo_contato_em)
SELECT 'telegram', 'Duplicado', telegram_chat_id, '', '', '', NOW(), NOW() FROM core_contato WHERE canal='telegram' LIMIT 1;
ROLLBACK TO a;
SAVEPOINT b;
-- 2) Abre uma conversa (ok) e tenta abrir a SEGUNDA para o mesmo contato -> uma_conversa_aberta_por_contato
INSERT INTO core_conversa (contato_id, canal, status, modo, motivo_escalonamento, comentario_avaliacao, iniciada_em, atualizada_em)
SELECT id, 'telegram', 'bot', 'menu', '', '', NOW(), NOW() FROM core_contato WHERE canal='telegram' LIMIT 1;
INSERT INTO core_conversa (contato_id, canal, status, modo, motivo_escalonamento, comentario_avaliacao, iniciada_em, atualizada_em)
SELECT id, 'telegram', 'fila', 'menu', '', '', NOW(), NOW() FROM core_contato WHERE canal='telegram' LIMIT 1;
ROLLBACK TO b;
-- 3) Conversa em atendimento humano sem atendente -> conversa_humano_tem_atendente
UPDATE core_conversa SET status='humano', atendente_id=NULL WHERE id=(SELECT MIN(id) FROM core_conversa);
ROLLBACK TO b;
-- 4) Avaliação fora de 1..5 -> conversa_avaliacao_1_a_5
UPDATE core_conversa SET avaliacao=7 WHERE id=(SELECT MIN(id) FROM core_conversa);
ROLLBACK TO b;
-- 5) Mensagem de 'atendente' sem dizer qual funcionário -> mensagem_atendente_identificado
INSERT INTO core_mensagem (conversa_id, remetente, texto, origem_resposta, criada_em) VALUES ((SELECT MIN(id) FROM core_conversa), 'atendente', 'oi', 'humano', NOW());
-- desfaz tudo
ROLLBACK;
