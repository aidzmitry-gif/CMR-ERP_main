-- Semantic projection for comparing received JSON with stored ledger rows.
-- Preserve raw Inbox.payload for replay; never use an application supplied hash.
CREATE OR REPLACE FUNCTION accounting.posting_text(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT btrim(value, E' \t\n\r\f' || chr(11)||chr(133)||chr(160)||chr(5760)||
    chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||
    chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288))
$$;
CREATE OR REPLACE FUNCTION accounting.posting_integer_value(value jsonb) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result numeric; raw text;
BEGIN
  IF value='null'::jsonb THEN RETURN NULL; END IF;
  IF value='true'::jsonb THEN RETURN 1; END IF;
  IF value='false'::jsonb THEN RETURN 0; END IF;
  raw:=accounting.posting_text(value#>>'{}');
  IF jsonb_typeof(value)='string' AND raw !~ '^[+-]?[0-9](_?[0-9])*(\.0+)?$' THEN
    RAISE EXCEPTION 'Invalid inbox integer model value';
  END IF;
  result:=raw::numeric;
  IF result<>trunc(result) THEN RAISE EXCEPTION 'Invalid inbox integer model value'; END IF;
  RETURN result;
END $$;
CREATE OR REPLACE FUNCTION accounting.posting_date_value(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE raw text; seconds numeric; result date;
BEGIN
  IF value='null'::jsonb THEN RETURN NULL; END IF;
  IF jsonb_typeof(value) NOT IN ('string','number') THEN RAISE EXCEPTION 'Invalid inbox date value'; END IF;
  raw:=value#>>'{}';
  IF raw ~ '^[+-]?[0-9]+(\.[0-9]+)?$' THEN
    seconds:=raw::numeric;
    IF abs(seconds)>20000000000 THEN seconds:=seconds/1000; END IF;
    IF seconds>=0 THEN seconds:=round(seconds,6); END IF;
    IF mod(seconds,86400)<>0 THEN RAISE EXCEPTION 'Inbox date requires midnight'; END IF;
    result:=DATE '1970-01-01'+(seconds/86400)::integer;
  ELSIF raw ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])([Tt ]00[:]00([:]00([.,](0{1,6}|000000[0-9]+))?)?([Zz]|[+-]([01][0-9]|2[0-3])[:]?[0-5][0-9])?)?$' THEN
    result:=left(raw,10)::date;
  ELSE RAISE EXCEPTION 'Invalid inbox date value'; END IF;
  IF result<DATE '0001-01-01' OR result>DATE '9999-12-31' THEN RAISE EXCEPTION 'Inbox date out of range'; END IF;
  RETURN to_char(result,'YYYY-MM-DD');
END $$;
CREATE OR REPLACE FUNCTION accounting.posting_body_projection(body jsonb, normalize_input boolean DEFAULT true) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb; row_value jsonb; projected jsonb; rows jsonb:='[]'; key text; dims jsonb;
BEGIN
  IF jsonb_typeof(body) IS DISTINCT FROM 'object' OR jsonb_typeof(body->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body';
  END IF;
  result:=jsonb_build_object('opening',false,'correction_of',NULL)||body;
  IF normalize_input THEN
    FOREACH key IN ARRAY ARRAY['source','operation','rule_version','explanation'] LOOP
      result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_text(result->>key)),'null'::jsonb));
    END LOOP;
  END IF;
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','correction_of'] LOOP
    result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_integer_value(result->key)),'null'::jsonb));
  END LOOP;
  FOREACH key IN ARRAY ARRAY['document_date','operation_date','posting_date'] LOOP
    result:=jsonb_set(result,ARRAY[key],COALESCE(to_jsonb(accounting.posting_date_value(result->key)),'null'::jsonb));
  END LOOP;
  result:=jsonb_set(result,'{opening}',CASE WHEN jsonb_typeof(result->'opening')='number'
    THEN to_jsonb((result->>'opening')::numeric=1)
    ELSE COALESCE(to_jsonb((result->>'opening')::boolean),'null'::jsonb) END);
  FOR row_value IN SELECT value FROM jsonb_array_elements(body->'lines') LOOP
    projected:=jsonb_build_object('dimensions','{}'::jsonb,'currency','BYN','original_amount',NULL,
      'rate',NULL,'rate_scale',NULL,'rate_date',NULL,'rate_source',NULL,'quantity',NULL,'cash_activity',NULL)||row_value;
    IF normalize_input THEN
      -- Literal fields side/cash_activity do not use Pydantic string stripping.
      FOREACH key IN ARRAY ARRAY['account','currency','rate_source'] LOOP
        projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(accounting.posting_text(projected->>key)),'null'::jsonb));
      END LOOP;
    END IF;
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(
        CASE WHEN normalize_input THEN accounting.inbox_decimal_model((projected->key)::json)::numeric
             ELSE (projected->>key)::numeric END),'null'::jsonb));
    END LOOP;
    projected:=jsonb_set(projected,'{rate_scale}',COALESCE(to_jsonb(accounting.posting_integer_value(projected->'rate_scale')),'null'::jsonb));
    projected:=jsonb_set(projected,'{rate_date}',COALESCE(to_jsonb(accounting.posting_date_value(projected->'rate_date')),'null'::jsonb));
    IF normalize_input THEN
      SELECT COALESCE(jsonb_object_agg(accounting.posting_text(k),accounting.posting_text(v)),'{}'::jsonb)
        INTO dims FROM jsonb_each_text(projected->'dimensions') d(k,v);
      projected:=jsonb_set(projected,'{dimensions}',dims);
    END IF;
    rows:=rows||jsonb_build_array(projected);
  END LOOP;
  RETURN jsonb_set(result,'{lines}',rows);
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_resolved_inbox_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.inbox WHERE entry_id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Resolved inbox posting body cannot receive additional lines';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER resolved_inbox_lines BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_resolved_inbox_lines();

-- JSONB numeric equality loses the int/float distinction used by schemas.exact.
-- Inspect raw JSON tokens before the effect projection converts them to numeric.
CREATE OR REPLACE FUNCTION accounting.validate_inbox_decimal_tokens(body json) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE line_value json; key text; token json;
BEGIN
  IF json_typeof(body->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body lines';
  END IF;
  FOR line_value IN SELECT value FROM json_array_elements(body->'lines') LOOP
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      token:=line_value->key;
      IF key<>'amount' AND (token IS NULL OR json_typeof(token)='null') THEN CONTINUE; END IF;
      IF token IS NULL OR json_typeof(token) NOT IN ('string','number')
          OR (json_typeof(token)='number' AND token::text !~ '^-?[0-9]+$') THEN
        RAISE EXCEPTION 'Inbox posting body requires exact decimal strings or integers';
      END IF;
    END LOOP;
  END LOOP;
END $$;

-- Preserve Decimal's scale/exponent in the replay model; SQL numeric equality
-- is used separately for comparing the actual accounting effect.
CREATE OR REPLACE FUNCTION accounting.inbox_decimal_model(value json) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE raw text; pieces text[]; coefficient text; exponent_value integer; adjusted integer;
  point integer; sign_value text:=''; fraction text; result text;
BEGIN
  IF json_typeof(value)='null' THEN RETURN NULL; END IF;
  IF json_typeof(value) NOT IN ('string','number')
     OR (json_typeof(value)='number' AND value::text !~ '^-?[0-9]+$') THEN
    RAISE EXCEPTION 'Invalid inbox decimal model token';
  END IF;
  raw:=replace(accounting.posting_text(value#>>'{}'),'_','');
  pieces:=regexp_match(raw,'^([+-]?)([0-9]*)(\.([0-9]*))?([eE]([+-]?[0-9]+))?$');
  IF pieces IS NULL OR COALESCE(pieces[2],'')||COALESCE(pieces[4],'')='' THEN
    RAISE EXCEPTION 'Invalid inbox decimal model value';
  END IF;
  IF pieces[1]='-' THEN sign_value:='-'; END IF;
  fraction:=COALESCE(pieces[4],'');
  coefficient:=ltrim(pieces[2]||fraction,'0');
  IF coefficient='' THEN coefficient:='0'; END IF;
  exponent_value:=COALESCE(pieces[6],'0')::integer-length(fraction);
  adjusted:=exponent_value+length(coefficient)-1;
  IF exponent_value>0 OR adjusted< -6 THEN
    result:=left(coefficient,1);
    IF length(coefficient)>1 THEN result:=result||'.'||substring(coefficient FROM 2); END IF;
    result:=result||'E'||CASE WHEN adjusted>=0 THEN '+' ELSE '' END||adjusted::text;
  ELSIF exponent_value=0 THEN result:=coefficient;
  ELSE
    point:=length(coefficient)+exponent_value;
    IF point>0 THEN result:=left(coefficient,point)||'.'||substring(coefficient FROM point+1);
    ELSE result:='0.'||repeat('0',-point)||coefficient; END IF;
  END IF;
  RETURN sign_value||result;
END $$;

CREATE OR REPLACE FUNCTION accounting.inbox_replay_model(body json) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE result jsonb; line_value json; projected jsonb; lines jsonb:='[]'; key text; n integer:=0;
BEGIN
  PERFORM accounting.validate_inbox_shape(body);
  PERFORM accounting.validate_inbox_decimal_tokens(body);
  result:=accounting.posting_body_projection(body::jsonb);
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','correction_of'] LOOP
    IF result->key<>'null'::jsonb THEN
      IF (result->>key)::numeric<>trunc((result->>key)::numeric) THEN
        RAISE EXCEPTION 'Invalid inbox integer model value';
      END IF;
      result:=jsonb_set(result,ARRAY[key],to_jsonb((result->>key)::numeric::bigint));
    END IF;
  END LOOP;
  FOR line_value IN SELECT value FROM json_array_elements(body->'lines') LOOP
    projected:=result->'lines'->n;
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      projected:=jsonb_set(projected,ARRAY[key],COALESCE(to_jsonb(accounting.inbox_decimal_model(line_value->key)),'null'::jsonb));
    END LOOP;
    IF projected->'rate_scale'<>'null'::jsonb THEN
      IF (projected->>'rate_scale')::numeric<>trunc((projected->>'rate_scale')::numeric) THEN
        RAISE EXCEPTION 'Invalid inbox rate scale model value';
      END IF;
      projected:=jsonb_set(projected,'{rate_scale}',to_jsonb((projected->>'rate_scale')::numeric::bigint));
    END IF;
    lines:=lines||jsonb_build_array(projected);
    n:=n+1;
  END LOOP;
  result:=jsonb_set(result,'{lines}',lines);
  PERFORM accounting.validate_inbox_model_bounds(result);
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_inbox_shape(body json) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE b jsonb:=body::jsonb; line_value jsonb; key text; v jsonb; limit_value integer;
BEGIN
  IF jsonb_typeof(b) IS DISTINCT FROM 'object' OR jsonb_typeof(b->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Invalid inbox posting body structure';
  END IF;
  IF jsonb_array_length(b->'lines') NOT BETWEEN 1 AND 1000
     OR b-ARRAY['source','source_version','operation','document_date','operation_date','posting_date',
         'policy_id','rule_version','explanation','lines','opening','correction_of']<>'{}'::jsonb THEN
    RAISE EXCEPTION 'Invalid inbox posting body fields';
  END IF;
  FOREACH key IN ARRAY ARRAY['source','operation','rule_version','explanation'] LOOP
    limit_value:=CASE key WHEN 'source' THEN 160 WHEN 'operation' THEN 60 WHEN 'rule_version' THEN 100 ELSE 1000 END;
    IF jsonb_typeof(b->key) IS DISTINCT FROM 'string' OR length(accounting.posting_text(b->>key)) NOT BETWEEN 1 AND limit_value THEN
      RAISE EXCEPTION 'Invalid inbox posting body string field';
    END IF;
  END LOOP;
  IF b ? 'opening' THEN
    v:=b->'opening';
    IF NOT (jsonb_typeof(v)='boolean' OR (jsonb_typeof(v)='number' AND v IN ('0'::jsonb,'1'::jsonb))
       OR (jsonb_typeof(v)='string' AND lower(v#>>'{}') IN ('0','1','off','on','no','yes','f','t','false','true','n','y'))) THEN
      RAISE EXCEPTION 'Invalid inbox posting body boolean field';
    END IF;
  END IF;
  FOR line_value IN SELECT value FROM jsonb_array_elements(b->'lines') LOOP
    IF jsonb_typeof(line_value) IS DISTINCT FROM 'object' OR line_value-ARRAY['account','side','amount','dimensions','currency',
        'original_amount','rate','rate_scale','rate_date','rate_source','quantity','cash_activity']<>'{}'::jsonb THEN
      RAISE EXCEPTION 'Invalid inbox posting body line fields';
    END IF;
    IF jsonb_typeof(line_value->'account') IS DISTINCT FROM 'string'
       OR accounting.posting_text(line_value->>'account') !~ '^[0-9]+(\.[0-9]+)*$'
       OR length(accounting.posting_text(line_value->>'account')) NOT BETWEEN 1 AND 32
       OR COALESCE(line_value->>'side','') NOT IN ('debit','credit') THEN
      RAISE EXCEPTION 'Invalid inbox posting body account or side';
    END IF;
    IF line_value ? 'currency' AND (jsonb_typeof(line_value->'currency') IS DISTINCT FROM 'string'
       OR accounting.posting_text(line_value->>'currency') !~ '^[A-Z]{3}$') THEN
      RAISE EXCEPTION 'Invalid inbox posting body currency';
    END IF;
    IF line_value ? 'rate_source' AND line_value->'rate_source'<>'null'::jsonb AND
       (jsonb_typeof(line_value->'rate_source')<>'string' OR length(accounting.posting_text(line_value->>'rate_source'))>200) THEN
      RAISE EXCEPTION 'Invalid inbox posting body rate source';
    END IF;
    IF line_value ? 'dimensions' THEN
      IF jsonb_typeof(line_value->'dimensions') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Invalid inbox posting body dimensions';
      END IF;
      FOR key,v IN SELECT * FROM jsonb_each(line_value->'dimensions') LOOP
        IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR accounting.posting_text(key)=''
           OR accounting.posting_text(translate(v#>>'{}',chr(28)||chr(29)||chr(30)||chr(31),'    '))=''
           OR length(accounting.posting_text(v#>>'{}')) NOT BETWEEN 1 AND 200 THEN
          RAISE EXCEPTION 'Invalid inbox posting body analytical value';
        END IF;
      END LOOP;
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_inbox_model_bounds(body jsonb) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE key text; line_value jsonb; v numeric; digits integer; places integer; fraction text; whole text;
  cents_numerator numeric; scale_value numeric; converted_cents numeric;
BEGIN
  FOREACH key IN ARRAY ARRAY['source_version','policy_id','document_date','operation_date','posting_date'] LOOP
    IF body->key IS NULL OR body->key='null'::jsonb THEN RAISE EXCEPTION 'Missing inbox posting body required field'; END IF;
  END LOOP;
  IF (body->>'source_version')::numeric<1 OR (body->>'policy_id')::numeric<=0
     OR COALESCE((body->>'correction_of')::numeric,1)<=0 THEN
    RAISE EXCEPTION 'Invalid inbox posting body identifier';
  END IF;
  FOR line_value IN SELECT value FROM jsonb_array_elements(body->'lines') LOOP
    FOREACH key IN ARRAY ARRAY['amount','original_amount','rate','quantity'] LOOP
      IF key<>'amount' AND (line_value->key IS NULL OR line_value->key='null'::jsonb) THEN CONTINUE; END IF;
      v:=(line_value->>key)::numeric;
      IF v IS NULL OR v::text IN ('NaN','Infinity','-Infinity') OR v<0
         OR (key IN ('rate','quantity') AND v=0) THEN
        RAISE EXCEPTION 'Invalid inbox posting body numeric value';
      END IF;
      whole:=ltrim(split_part(v::text,'.',1),'-0');
      fraction:=rtrim(split_part(v::text,'.',2),'0');
      digits:=CASE WHEN key IN ('amount','original_amount') THEN 20 ELSE 24 END;
      places:=CASE WHEN key IN ('amount','original_amount') THEN 2 ELSE 6 END;
      IF length(whole)+length(fraction)>digits OR length(fraction)>places THEN
        RAISE EXCEPTION 'Invalid inbox posting body numeric precision';
      END IF;
    END LOOP;
    IF COALESCE((line_value->>'rate_scale')::numeric,1)<=0
       OR (line_value->>'rate_scale')::numeric>2147483647
       OR (line_value->'cash_activity'<>'null'::jsonb AND line_value->>'cash_activity' NOT IN ('operating','investing','financing','internal')) THEN
      RAISE EXCEPTION 'Invalid inbox posting body scale or cash activity';
    END IF;
    IF line_value->>'currency'='BYN' THEN
      FOREACH key IN ARRAY ARRAY['original_amount','rate','rate_scale','rate_date','rate_source'] LOOP
        IF line_value->key<>'null'::jsonb THEN RAISE EXCEPTION 'BYN inbox posting body cannot carry FX metadata'; END IF;
      END LOOP;
    ELSE
      FOREACH key IN ARRAY ARRAY['original_amount','rate','rate_scale','rate_date','rate_source'] LOOP
        IF line_value->key IS NULL OR line_value->key='null'::jsonb THEN RAISE EXCEPTION 'Incomplete inbox posting body FX metadata'; END IF;
      END LOOP;
      -- Compare cents using quotient/remainder: numeric division may round a
      -- large quotient before round(...,2), changing a below-half-cent amount.
      cents_numerator:=(line_value->>'original_amount')::numeric*(line_value->>'rate')::numeric*100;
      scale_value:=(line_value->>'rate_scale')::numeric;
      converted_cents:=div(cents_numerator,scale_value)+
        CASE WHEN mod(cents_numerator,scale_value)*2>=scale_value THEN 1 ELSE 0 END;
      IF line_value->>'rate_source'='' OR converted_cents<>(line_value->>'amount')::numeric*100 THEN
        RAISE EXCEPTION 'Inbox posting body FX conversion mismatch';
      END IF;
    END IF;
  END LOOP;
END $$;
