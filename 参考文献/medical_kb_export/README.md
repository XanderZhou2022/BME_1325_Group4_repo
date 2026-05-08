# Medical Knowledge Base Export

This folder contains a structured Doctor Knowledge Base (Doctor KB) designed for clinical decision support and RAG (Retrieval-Augmented Generation) systems. It includes standardized data for common medical complaints, ready for integration into other projects.

## 📂 Directory Structure

| Directory/File | Description |
|----------------|-------------|
| `sources/` | Core YAML files defining symptoms, red flags, and questions. |
| `ontologies/` | Schema definitions for intents and slots. |
| `compiled/` | JSONL files for RAG embedding (explanations, questions, red flags). |
| `indices/` | Lexical search indices. |
| `manifests/` | Registry of complaints and evaluation sets. |
| `README.md` | This file. |

## 🏥 Covered Complaints (8 Total)

The `sources/` directory contains YAML files for the following conditions:
1.  `abdominal_pain.yaml`
2.  `back_pain.yaml`
3.  `dizziness.yaml`
4.  `dysuria.yaml`
5.  `fever.yaml`
6.  `headache.yaml`
7.  `nausea_vomiting.yaml`
8.  `palpitations.yaml`

## 📝 Data Schema

Each complaint file includes:
* **Aliases & Keywords**: For matching and search.
* **Question Graph**: Structured clinical questions with bilingual text (Chinese/English).
* **Red Flags**: Critical symptoms requiring urgent care, with rationale.
* **Exam Focus & Test Considerations**: Recommended physical exams, labs, and imaging.
* **Explanations**: Patient-facing reasons for tests and questions.
* **Source Metadata**: Evidence level, curation info, and guidelines.

## 🛠️ Usage Guide

### 1. Integration (YAML)
Load `sources/*.yaml` using any YAML parser. These files provide the raw logic for clinical interviews.

**Python Example:**
```python
import yaml
import glob

kb = {}
for f in glob.glob("sources/*.yaml"):
    data = yaml.safe_load(open(f))
    kb[data["complaint_id"]] = data
```

### 2. RAG Pipeline (JSONL)
Use `compiled/*.jsonl` files to build vector embeddings for semantic search. Each line is a JSON object ready for embedding.

### 3. Ontology & Search
* `ontologies/`: Use `intent_ontology.yaml` and `slot_ontology.yaml` to validate data structures.
* `indices/`: Use `*_lex.json` for fast keyword-based retrieval.
* `manifests/complaint_registry.yaml`: The master list of all supported complaints.

---
*Generated for use in external projects. Original source: BME1325 Group Repo.*