-- Xdocs standalone schema (tables prefixed 'Docs_').
-- Generated from the ORM models - do not edit by hand.
-- Regenerate: DB_TABLE_PREFIX=Docs_ python deploy/standalone/generate_schema.py

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE "Docs_analytics_event" (
	id UUID NOT NULL, 
	tenant_id UUID, 
	type VARCHAR(32) NOT NULL, 
	subject_id UUID, 
	data JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX "ix_Docs_analytics_event_type" ON "Docs_analytics_event" (type);

CREATE TABLE "Docs_export_job" (
	id UUID NOT NULL, 
	scope_type VARCHAR(16) NOT NULL, 
	scope_id VARCHAR(128), 
	status VARCHAR(16) NOT NULL, 
	content BYTEA, 
	content_type VARCHAR(64) NOT NULL, 
	page_count INTEGER NOT NULL, 
	error TEXT, 
	created_by UUID, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE "Docs_llm_artifact" (
	id UUID NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	markdown TEXT NOT NULL, 
	created_by UUID, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE "Docs_space" (
	id UUID NOT NULL, 
	tenant_id UUID, 
	slug VARCHAR(128) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	description TEXT, 
	default_locale VARCHAR(16) NOT NULL, 
	color VARCHAR(16), 
	landing_blocks JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX "ix_Docs_space_slug" ON "Docs_space" (slug);

CREATE TABLE "Docs_translation_cache" (
	id UUID NOT NULL, 
	page_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	locale VARCHAR(16) NOT NULL, 
	html TEXT NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_translation_cache UNIQUE (page_id, revision, locale)
);

CREATE INDEX "ix_Docs_translation_cache_page_id" ON "Docs_translation_cache" (page_id);

CREATE TABLE "Docs_media_asset" (
	id UUID NOT NULL, 
	space_id UUID, 
	filename VARCHAR(256) NOT NULL, 
	content_type VARCHAR(128) NOT NULL, 
	size INTEGER NOT NULL, 
	content BYTEA NOT NULL, 
	uploaded_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(space_id) REFERENCES "Docs_space" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_product_version" (
	id UUID NOT NULL, 
	space_id UUID NOT NULL, 
	label VARCHAR(64) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	sort_order INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_version_space_label UNIQUE (space_id, label), 
	FOREIGN KEY(space_id) REFERENCES "Docs_space" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_book" (
	id UUID NOT NULL, 
	space_id UUID NOT NULL, 
	version_id UUID NOT NULL, 
	slug VARCHAR(128) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_book_version_slug UNIQUE (version_id, slug), 
	FOREIGN KEY(space_id) REFERENCES "Docs_space" (id) ON DELETE CASCADE, 
	FOREIGN KEY(version_id) REFERENCES "Docs_product_version" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_section" (
	id UUID NOT NULL, 
	book_id UUID NOT NULL, 
	slug VARCHAR(128) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_section_book_slug UNIQUE (book_id, slug), 
	FOREIGN KEY(book_id) REFERENCES "Docs_book" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_page" (
	id UUID NOT NULL, 
	book_id UUID NOT NULL, 
	section_id UUID, 
	parent_page_id UUID, 
	slug VARCHAR(128) NOT NULL, 
	sort_order INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_page_parent_slug UNIQUE (book_id, parent_page_id, slug), 
	FOREIGN KEY(book_id) REFERENCES "Docs_book" (id) ON DELETE CASCADE, 
	FOREIGN KEY(section_id) REFERENCES "Docs_section" (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_page_id) REFERENCES "Docs_page" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_page_translation" (
	id UUID NOT NULL, 
	page_id UUID NOT NULL, 
	locale VARCHAR(16) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	markdown TEXT NOT NULL, 
	published_markdown TEXT, 
	html_cached TEXT, 
	headings JSON, 
	translation_status VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	published_revision INTEGER, 
	published_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_translation_page_locale UNIQUE (page_id, locale), 
	FOREIGN KEY(page_id) REFERENCES "Docs_page" (id) ON DELETE CASCADE
);

CREATE TABLE "Docs_doc_chunk" (
	id UUID NOT NULL, 
	page_translation_id UUID NOT NULL, 
	page_id UUID NOT NULL, 
	space_slug VARCHAR(128) NOT NULL, 
	book_id UUID NOT NULL, 
	locale VARCHAR(16) NOT NULL, 
	page_title VARCHAR(512) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	anchor JSON, 
	embedding JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(page_translation_id) REFERENCES "Docs_page_translation" (id) ON DELETE CASCADE
);

CREATE INDEX "ix_Docs_doc_chunk_space_slug" ON "Docs_doc_chunk" (space_slug);
CREATE INDEX "ix_Docs_doc_chunk_page_id" ON "Docs_doc_chunk" (page_id);
CREATE INDEX "ix_Docs_doc_chunk_book_id" ON "Docs_doc_chunk" (book_id);

CREATE TABLE "Docs_page_revision" (
	id UUID NOT NULL, 
	page_translation_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	markdown TEXT NOT NULL, 
	author_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_revision_translation_rev UNIQUE (page_translation_id, revision), 
	FOREIGN KEY(page_translation_id) REFERENCES "Docs_page_translation" (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS "ix_Docs_doc_chunk_ts" ON "Docs_doc_chunk" USING gin (to_tsvector('simple', content));
