#!/usr/bin/env python
"""Create and maintain a Vertex AI RAG Engine corpus.

Self-contained (no project imports) so it can run as a Cloud Build step using
the application image. Handles minor SDK churn across google-cloud-aiplatform
versions for embedding/chunking config.

Usage:
  python scripts/manage_corpus.py sync \
      --display-name rag-agent-corpus \
      --gcs-source gs://my-bucket/docs/

  python scripts/manage_corpus.py list
  python scripts/manage_corpus.py delete --display-name rag-agent-corpus

Environment:
  GOOGLE_CLOUD_PROJECT   (required)
  GOOGLE_CLOUD_LOCATION  (default: us-central1)
"""

from __future__ import annotations

import argparse
import os
import sys

import vertexai
from vertexai.preview import rag

EMBEDDING_MODEL = "publishers/google/models/text-embedding-005"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 100


def _init() -> tuple[str, str]:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    if not project:
        sys.exit("GOOGLE_CLOUD_PROJECT must be set.")
    vertexai.init(project=project, location=location)
    return project, location


def find_corpus(display_name: str):
    for corpus in rag.list_corpora():
        if corpus.display_name == display_name:
            return corpus
    return None


def create_corpus(display_name: str):
    """Create a corpus in Serverless mode."""
    # Serverless mode is required for new projects in us-central1.
    # Use display_only_rag_store_config to explicitly enable Serverless.
    if hasattr(rag, "RagVectorDbConfig"):
        # Newer SDK with Serverless support.
        try:
            return rag.create_corpus(
                display_name=display_name,
                display_only_rag_store_config=rag.RagVectorDbConfig(),
            )
        except TypeError:
            # Fallback: try without explicit Serverless config.
            pass

    # Older SDK: use embedding_model_config kwarg.
    if hasattr(rag, "EmbeddingModelConfig"):
        embedding = rag.EmbeddingModelConfig(publisher_model=EMBEDDING_MODEL)
        return rag.create_corpus(display_name=display_name, embedding_model_config=embedding)

    # Last resort: minimal config.
    return rag.create_corpus(display_name=display_name)


def import_files(corpus_name: str, gcs_source: str) -> None:
    """Import files from GCS into the corpus, tolerating the chunking API change."""
    if hasattr(rag, "TransformationConfig"):
        transformation = rag.TransformationConfig(
            chunking_config=rag.ChunkingConfig(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        )
        rag.import_files(
            corpus_name=corpus_name,
            paths=[gcs_source],
            transformation_config=transformation,
        )
    else:
        rag.import_files(
            corpus_name=corpus_name,
            paths=[gcs_source],
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )


def cmd_sync(args: argparse.Namespace) -> None:
    _init()
    corpus = find_corpus(args.display_name)
    if corpus is None:
        print(f"Creating corpus {args.display_name!r} ...")
        corpus = create_corpus(args.display_name)
        print(f"Created: {corpus.name}")
    else:
        print(f"Found existing corpus: {corpus.name}")

    if args.gcs_source:
        print(f"Importing files from {args.gcs_source} ...")
        import_files(corpus.name, args.gcs_source)
        print("Import request submitted.")

    # Emit the resource name so callers (e.g. Cloud Build) can capture it.
    print(f"RAG_CORPUS={corpus.name}")


def cmd_list(_: argparse.Namespace) -> None:
    _init()
    for corpus in rag.list_corpora():
        print(f"{corpus.display_name}\t{corpus.name}")


def cmd_delete(args: argparse.Namespace) -> None:
    _init()
    corpus = find_corpus(args.display_name)
    if corpus is None:
        print(f"No corpus named {args.display_name!r}.")
        return
    rag.delete_corpus(name=corpus.name)
    print(f"Deleted {corpus.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Create corpus if missing and import files.")
    p_sync.add_argument("--display-name", required=True)
    p_sync.add_argument("--gcs-source", default="", help="gs:// path or prefix to import.")
    p_sync.set_defaults(func=cmd_sync)

    p_list = sub.add_parser("list", help="List corpora in the project/location.")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="Delete a corpus by display name.")
    p_del.add_argument("--display-name", required=True)
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
