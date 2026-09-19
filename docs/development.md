# Fluxo de desenvolvimento

## Branches

O repositório usa `main` como branch de integração. Cada milestone de implementação recebe uma única branch de integração criada a partir da `main` mais recente.

```text
milestone/foundation
milestone/artifact-explorer
milestone/ingestion-console
milestone/pipeline-console
```

Branches pequenas por issue são opcionais. Quando existirem, são integradas na branch da milestone, nunca diretamente em `main`.

A promoção de uma milestone ocorre somente por Pull Request:

```text
milestone/<slug> -> main
```

O PR deve resumir a milestone, referenciar suas issues, passar CI e satisfazer os critérios de aceitação antes do merge.

A próxima branch de milestone só deve nascer da `main` depois que a anterior for promovida, evitando branches long-lived desnecessariamente defasadas.

## Commits

Commits devem referenciar a issue correspondente quando aplicável:

```text
feat(artifact): add observation table

Refs: #7
```

## Quality gates

Antes de promover para `main`:

```bash
make check
make build
```

CI executa as mesmas verificações.

## Disciplina de escopo

- não criar módulos vazios para milestones futuras;
- não implementar UI para capability sem API pública estável no core;
- preferir fake clients determinísticos nos testes;
- Artifact Explorer deve funcionar sem GPU, modelos ou rede;
- usar apenas contratos públicos do `contextmap2`;
- a TUI não deve se tornar uma segunda implementação de runtime ou Ingestion.
