-- =====================================================================
-- ops/005_silver_watermark.sql — watermark por instante de carga (Silver)
-- A Silver é incremental por `carregado_em` da Bronze (precisão de tempo, não de data).
-- =====================================================================
ALTER TABLE ops.controle_ingestao ADD COLUMN IF NOT EXISTS ultimo_carregado_em TIMESTAMPTZ;
