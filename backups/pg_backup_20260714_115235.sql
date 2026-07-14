--
-- PostgreSQL database cluster dump
--

\restrict 1oAZgXGVCAqNTbJJbDGAtjziKItoZODFaUvTVP46PzW1D8jQ9pKUwfQUqQjzFGg

SET default_transaction_read_only = off;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

--
-- Roles
--

CREATE ROLE factcheck;
ALTER ROLE factcheck WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN REPLICATION BYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:dyTVR9lwFxK30cIUP2kb4g==$rBG903hqETllRxJIetDb/4HjmVAQijB0ts36qF2yL7I=:LV2nNAYn03vfXx+LEENq7rcvY2qiP63szJ5LHoBtWco=';

--
-- User Configurations
--








\unrestrict 1oAZgXGVCAqNTbJJbDGAtjziKItoZODFaUvTVP46PzW1D8jQ9pKUwfQUqQjzFGg

--
-- Databases
--

--
-- Database "template1" dump
--

\connect template1

--
-- PostgreSQL database dump
--

\restrict Fpc4JfS2HjVWfcjjujnaKOYsiesACIdcULScTZnr3Tz2KdqoBdAgaCXIAKTMWVC

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- PostgreSQL database dump complete
--

\unrestrict Fpc4JfS2HjVWfcjjujnaKOYsiesACIdcULScTZnr3Tz2KdqoBdAgaCXIAKTMWVC

--
-- Database "factcheck" dump
--

--
-- PostgreSQL database dump
--

\restrict w7AO8XN0WdWxVt9rAngv27ZAfbFNfUUyMtHKlSFtlQe97ecliEqJTVwyMFrGCds

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: factcheck; Type: DATABASE; Schema: -; Owner: factcheck
--

CREATE DATABASE factcheck WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'en_US.utf8';


ALTER DATABASE factcheck OWNER TO factcheck;

\unrestrict w7AO8XN0WdWxVt9rAngv27ZAfbFNfUUyMtHKlSFtlQe97ecliEqJTVwyMFrGCds
\connect factcheck
\restrict w7AO8XN0WdWxVt9rAngv27ZAfbFNfUUyMtHKlSFtlQe97ecliEqJTVwyMFrGCds

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: job_status; Type: TYPE; Schema: public; Owner: factcheck
--

CREATE TYPE public.job_status AS ENUM (
    'queued',
    'processing',
    'completed',
    'failed',
    'dlq'
);


ALTER TYPE public.job_status OWNER TO factcheck;

--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: factcheck
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.set_updated_at() OWNER TO factcheck;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: claims; Type: TABLE; Schema: public; Owner: factcheck
--

CREATE TABLE public.claims (
    claim_id uuid DEFAULT gen_random_uuid() NOT NULL,
    verify_job_id uuid NOT NULL,
    claim_index integer NOT NULL,
    claim_text text NOT NULL,
    source_url text,
    metadata jsonb DEFAULT '{}'::jsonb,
    verdict text,
    confidence numeric(4,3),
    evidence_urls jsonb,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT claims_claim_index_check CHECK ((claim_index >= 0))
);


ALTER TABLE public.claims OWNER TO factcheck;

--
-- Name: TABLE claims; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON TABLE public.claims IS 'Individual claims belonging to a verification job.';


--
-- Name: COLUMN claims.claim_index; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON COLUMN public.claims.claim_index IS 'Zero-based position within the submitted claims array.';


--
-- Name: COLUMN claims.verdict; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON COLUMN public.claims.verdict IS 'Fact-check verdict — populated by worker (Checkpoint B+).';


--
-- Name: dlq; Type: TABLE; Schema: public; Owner: factcheck
--

CREATE TABLE public.dlq (
    dlq_id uuid DEFAULT gen_random_uuid() NOT NULL,
    verify_job_id uuid NOT NULL,
    ingest_id text NOT NULL,
    reason text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.dlq OWNER TO factcheck;

--
-- Name: TABLE dlq; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON TABLE public.dlq IS 'Dead-letter entries for jobs that failed irrecoverably after all retries.';


--
-- Name: verifications; Type: TABLE; Schema: public; Owner: factcheck
--

CREATE TABLE public.verifications (
    verify_job_id uuid DEFAULT gen_random_uuid() NOT NULL,
    ingest_id text NOT NULL,
    status public.job_status DEFAULT 'queued'::public.job_status NOT NULL,
    claim_count integer NOT NULL,
    priority smallint DEFAULT 0 NOT NULL,
    callback_url text,
    results jsonb,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT verifications_claim_count_check CHECK ((claim_count > 0)),
    CONSTRAINT verifications_priority_check CHECK (((priority >= 0) AND (priority <= 10)))
);


ALTER TABLE public.verifications OWNER TO factcheck;

--
-- Name: TABLE verifications; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON TABLE public.verifications IS 'One row per fact-checking job submitted via POST /verify.';


--
-- Name: COLUMN verifications.verify_job_id; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON COLUMN public.verifications.verify_job_id IS 'Primary key; also used as the RQ job ID.';


--
-- Name: COLUMN verifications.ingest_id; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON COLUMN public.verifications.ingest_id IS 'Upstream idempotency key from the ingest pipeline.';


--
-- Name: COLUMN verifications.results; Type: COMMENT; Schema: public; Owner: factcheck
--

COMMENT ON COLUMN public.verifications.results IS 'JSONB array of ClaimResult objects written by the worker.';


--
-- Data for Name: claims; Type: TABLE DATA; Schema: public; Owner: factcheck
--

COPY public.claims (claim_id, verify_job_id, claim_index, claim_text, source_url, metadata, verdict, confidence, evidence_urls, error, created_at, updated_at) FROM stdin;
8922e00d-4056-4a06-9261-898e791cea3b	00000000-0000-0000-0000-000000000002	0	The moon landing happened in 1969.	\N	{}	\N	\N	\N	\N	2026-07-13 22:02:21.67929+00	2026-07-13 22:02:21.67929+00
\.


--
-- Data for Name: dlq; Type: TABLE DATA; Schema: public; Owner: factcheck
--

COPY public.dlq (dlq_id, verify_job_id, ingest_id, reason, payload, created_at) FROM stdin;
\.


--
-- Data for Name: verifications; Type: TABLE DATA; Schema: public; Owner: factcheck
--

COPY public.verifications (verify_job_id, ingest_id, status, claim_count, priority, callback_url, results, error_message, created_at, updated_at) FROM stdin;
00000000-0000-0000-0000-000000000001	seed-ingest-001	completed	2	0	\N	[{"error": null, "verdict": "FALSE", "claim_text": "The Earth is flat.", "confidence": 0.99, "claim_index": 0, "evidence_urls": []}, {"error": null, "verdict": "TRUE", "claim_text": "Water boils at 100°C at sea level.", "confidence": 0.99, "claim_index": 1, "evidence_urls": []}]	\N	2026-07-13 21:02:21.669069+00	2026-07-13 22:02:21.669069+00
00000000-0000-0000-0000-000000000002	seed-ingest-002	queued	1	5	\N	\N	\N	2026-07-13 22:02:21.676064+00	2026-07-13 22:02:21.676064+00
\.


--
-- Name: claims claims_pkey; Type: CONSTRAINT; Schema: public; Owner: factcheck
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (claim_id);


--
-- Name: claims claims_verify_job_id_claim_index_key; Type: CONSTRAINT; Schema: public; Owner: factcheck
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_verify_job_id_claim_index_key UNIQUE (verify_job_id, claim_index);


--
-- Name: dlq dlq_pkey; Type: CONSTRAINT; Schema: public; Owner: factcheck
--

ALTER TABLE ONLY public.dlq
    ADD CONSTRAINT dlq_pkey PRIMARY KEY (dlq_id);


--
-- Name: verifications verifications_pkey; Type: CONSTRAINT; Schema: public; Owner: factcheck
--

ALTER TABLE ONLY public.verifications
    ADD CONSTRAINT verifications_pkey PRIMARY KEY (verify_job_id);


--
-- Name: ix_claims_verify_job_id; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE INDEX ix_claims_verify_job_id ON public.claims USING btree (verify_job_id);


--
-- Name: ix_dlq_created_at; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE INDEX ix_dlq_created_at ON public.dlq USING btree (created_at DESC);


--
-- Name: ix_dlq_verify_job_id; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE INDEX ix_dlq_verify_job_id ON public.dlq USING btree (verify_job_id);


--
-- Name: ix_verifications_created_at; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE INDEX ix_verifications_created_at ON public.verifications USING btree (created_at DESC);


--
-- Name: ix_verifications_status; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE INDEX ix_verifications_status ON public.verifications USING btree (status) WHERE (status = ANY (ARRAY['queued'::public.job_status, 'processing'::public.job_status]));


--
-- Name: uix_verifications_ingest_id; Type: INDEX; Schema: public; Owner: factcheck
--

CREATE UNIQUE INDEX uix_verifications_ingest_id ON public.verifications USING btree (ingest_id);


--
-- Name: claims trg_claims_updated_at; Type: TRIGGER; Schema: public; Owner: factcheck
--

CREATE TRIGGER trg_claims_updated_at BEFORE UPDATE ON public.claims FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: verifications trg_verifications_updated_at; Type: TRIGGER; Schema: public; Owner: factcheck
--

CREATE TRIGGER trg_verifications_updated_at BEFORE UPDATE ON public.verifications FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: claims claims_verify_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: factcheck
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_verify_job_id_fkey FOREIGN KEY (verify_job_id) REFERENCES public.verifications(verify_job_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict w7AO8XN0WdWxVt9rAngv27ZAfbFNfUUyMtHKlSFtlQe97ecliEqJTVwyMFrGCds

--
-- Database "postgres" dump
--

\connect postgres

--
-- PostgreSQL database dump
--

\restrict fhoicWqNlCc51LT2vK981bSO6GIzRPp7NUMtf5hVwniG6AdPfrpMrAvFCmM3Qdk

-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- PostgreSQL database dump complete
--

\unrestrict fhoicWqNlCc51LT2vK981bSO6GIzRPp7NUMtf5hVwniG6AdPfrpMrAvFCmM3Qdk

--
-- PostgreSQL database cluster dump complete
--

