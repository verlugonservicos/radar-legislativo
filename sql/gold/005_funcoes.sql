-- =====================================================================
-- gold/005_funcoes.sql — funções de apresentação usadas na carga da Gold. Idempotente.
-- =====================================================================

-- "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS" → "Locação ou Fretamento de Veículos".
-- Iniciais maiúsculas (initcap, que respeita acentos e hífens); conectivos em minúsculas fora da
-- 1ª palavra; siglas societárias e palavras com dígitos preservadas em maiúsculas.
CREATE OR REPLACE FUNCTION gold.titulo(texto text) RETURNS text
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    palavras text[];
    p text;
    i int;
    saida text[] := '{}';
    conectivos text[] := ARRAY['a','à','ao','aos','as','às','com','da','das','de','do','dos','e','em',
                               'na','nas','no','nos','o','os','ou','para','pela','pelas','pelo','pelos',
                               'por','sem','sob','um','uma'];
    siglas text[] := ARRAY['S/A','S.A.','S.A','S/A.','SA','ME','EPP','EIRELI','LTDA-ME','CNPJ','CPF',
                           'TV','FM','AM','II','III','IV','VI','VII','VIII','IX','XI','XII','SIGEPA','TAM'];
BEGIN
    IF texto IS NULL OR btrim(texto) = '' THEN
        RETURN texto;
    END IF;
    -- vírgula colada na palavra seguinte ("Hospedagem ,Exceto") → "Hospedagem, Exceto"
    texto := regexp_replace(regexp_replace(texto, '\s+,', ',', 'g'), ',(\S)', ', \1', 'g');
    palavras := regexp_split_to_array(btrim(regexp_replace(texto, '\s+', ' ', 'g')), ' ');
    FOR i IN 1 .. array_length(palavras, 1) LOOP
        p := palavras[i];
        IF upper(p) = ANY (siglas) OR p ~ '[0-9]' THEN
            saida := saida || upper(p);
        ELSIF i > 1 AND lower(p) = ANY (conectivos) THEN
            saida := saida || lower(p);
        ELSE
            saida := saida || initcap(p);
        END IF;
    END LOOP;
    RETURN array_to_string(saida, ' ');
END;
$$;
