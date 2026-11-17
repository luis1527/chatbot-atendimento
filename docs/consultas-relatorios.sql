-- Consultas de relatório (PostgreSQL). Todas testadas no banco local populado com
--   python manage.py popular_demo --conversas
-- Rodar tudo:  psql chatbot_atendimento -f docs/consultas-relatorios.sql
-- Explicação de cada uma: docs/modelo-de-dados.md, seção "Consultas para relatórios".

-- Q1 perguntas por intencao
SELECT i.nome AS intencao, COUNT(m.id) AS mensagens,
       ROUND(AVG(m.confianca)::numeric, 2) AS confianca_media
FROM core_mensagem m
JOIN core_intencao i ON i.id = m.intencao_id
WHERE m.remetente = 'cliente'
GROUP BY i.nome
ORDER BY mensagens DESC;
-- Q2 tempo medio na fila
SELECT c.canal, COUNT(*) AS conversas_atendidas,
       ROUND(AVG(EXTRACT(EPOCH FROM (c.assumida_em - c.escalada_em)) / 60)::numeric, 1) AS minutos_medios_na_fila,
       ROUND(MAX(EXTRACT(EPOCH FROM (c.assumida_em - c.escalada_em)) / 60)::numeric, 1) AS pior_caso_min
FROM core_conversa c
WHERE c.escalada_em IS NOT NULL AND c.assumida_em IS NOT NULL
GROUP BY c.canal;
-- Q3 nota media por atendente
SELECT COALESCE(NULLIF(u.apelido, ''), u.username) AS atendente,
       COUNT(c.id) AS conversas, COUNT(c.avaliacao) AS avaliadas,
       ROUND(AVG(c.avaliacao)::numeric, 2) AS nota_media
FROM core_usuario u
LEFT JOIN core_conversa c ON c.atendente_id = u.id
WHERE u.cargo = 'atendente'
GROUP BY u.id, atendente
ORDER BY nota_media DESC NULLS LAST;
-- Q4 tickets por status
SELECT status, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE prioridade = 'alta') AS alta_prioridade
FROM core_ticket
GROUP BY status
ORDER BY total DESC;
-- Q5 bot x humano
SELECT CASE WHEN atendente_id IS NULL THEN 'Resolvida pelo bot' ELSE 'Precisou de humano' END AS tipo,
       COUNT(*) AS conversas,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS percentual
FROM core_conversa
WHERE status = 'encerrada'
GROUP BY 1;
-- Q6 faq mais usado
SELECT f.pergunta, cat.nome AS categoria, COUNT(m.id) AS vezes_respondida
FROM core_mensagem m
JOIN core_perguntafaq f ON f.id = m.faq_id
JOIN core_categoriafaq cat ON cat.id = f.categoria_id
GROUP BY f.id, f.pergunta, cat.nome
ORDER BY vezes_respondida DESC
LIMIT 5;
-- Q7 conversas por dia
SELECT DATE(iniciada_em AT TIME ZONE 'America/Sao_Paulo') AS dia, COUNT(*) AS conversas,
       COUNT(*) FILTER (WHERE canal = 'telegram') AS telegram,
       COUNT(*) FILTER (WHERE canal = 'web') AS site
FROM core_conversa
GROUP BY dia
ORDER BY dia DESC
LIMIT 7;
-- Q8 historico de uma conversa (JOIN mensagens + contato)
SELECT m.criada_em, m.remetente, COALESCE(NULLIF(u.apelido,''), u.username) AS atendente, LEFT(m.texto, 50) AS texto
FROM core_mensagem m
JOIN core_conversa c ON c.id = m.conversa_id
JOIN core_contato ct ON ct.id = c.contato_id
LEFT JOIN core_usuario u ON u.id = m.atendente_id
WHERE c.id = (SELECT MIN(id) FROM core_conversa)
ORDER BY m.criada_em, m.id;
-- Q9 fila agora
SELECT c.id, ct.nome AS cliente, c.canal, c.motivo_escalonamento,
       ROUND(EXTRACT(EPOCH FROM (NOW() - c.escalada_em)) / 60) AS minutos_esperando
FROM core_conversa c
JOIN core_contato ct ON ct.id = c.contato_id
WHERE c.status = 'fila'
ORDER BY c.escalada_em;
-- Q10 verificacao de integridade: nada deve voltar
SELECT contato_id, COUNT(*) FROM core_conversa WHERE status <> 'encerrada' GROUP BY contato_id HAVING COUNT(*) > 1;
