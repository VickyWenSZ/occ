# OpenAI Responses API Guide (GPT-5 / GPT-5-mini)

> **IMPORTANTE**: Questo file documenta le differenze critiche tra la vecchia Chat Completions API e la nuova Responses API di OpenAI, necessaria per i modelli GPT-5.

## Perché usare Responses API?

OpenAI raccomanda la **Responses API** per tutti i nuovi progetti con GPT-5:
- **Più veloce**: Latenza ridotta (TTFT - Time To First Token)
- **Più potente**: Supporto nativo per reasoning traces, tool calling avanzato
- **Gestione stato efficiente**: Il server gestisce il contesto conversazionale

## Endpoint

```
POST https://api.openai.com/v1/responses
```

⚠️ **NON** usare `/v1/chat/completions` con GPT-5!

## Struttura Request

### Differenze chiave vs Chat Completions

| Chat Completions (legacy) | Responses API (GPT-5) |
|---------------------------|----------------------|
| `messages: [...]` | `input: [...]` |
| `max_tokens` | `max_output_tokens` |
| `response_format: { type: "json_object" }` | `text: { format: { type: "json_object" } }` |
| `temperature: 0.7` | ❌ Non supportato da GPT-5-mini (default: 1) |

### Esempio Request

```typescript
const response = await fetch("https://api.openai.com/v1/responses", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${OPENAI_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "gpt-5-mini",  // o "gpt-5"
    input: [
      { role: "system", content: "You are a helpful assistant." },
      { role: "user", content: "Hello!" }
    ],
    max_output_tokens: 2000,
    // Per output JSON strutturato:
    text: { format: { type: "json_object" } },
  }),
});
```

## 🔴 REQUISITO CRITICO: Parola "JSON" nel Prompt

**IMPORTANTE**: Quando usi `text: { format: { type: "json_object" } }`, OpenAI **RICHIEDE** che il prompt contenga la parola **"json"** (case-insensitive).

### ❌ SBAGLIATO - Causa 400 Bad Request

```typescript
input: [
  { role: "system", content: "You extract facts from text." },
  { role: "user", content: "Extract facts from: I live in Rome." }
],
text: { format: { type: "json_object" } }  // ❌ 400 Bad Request!
```

**Errore restituito:**
```json
{
  "error": {
    "message": "Response input messages must contain the word 'json' in some form to use 'text.format' of type 'json_object'.",
    "type": "invalid_request_error",
    "param": "input"
  }
}
```

### ✅ CORRETTO - Include "json" nel prompt

```typescript
// Opzione 1: Nel prompt utente
input: [
  { role: "system", content: "You extract facts from text." },
  { role: "user", content: "Extract facts from: I live in Rome.\n\nReturn your response as valid JSON." }
],
text: { format: { type: "json_object" } }  // ✅ OK!

// Opzione 2: Nel system prompt
input: [
  { role: "system", content: "You extract facts from text. Output JSON only." },
  { role: "user", content: "Extract facts from: I live in Rome." }
],
text: { format: { type: "json_object" } }  // ✅ OK!

// Opzione 3: In entrambi (più sicuro)
input: [
  { role: "system", content: "You extract facts. Output valid JSON." },
  { role: "user", content: "Extract facts and return JSON: I live in Rome." }
],
text: { format: { type: "json_object" } }  // ✅ OK!
```

### Best Practice

**Pattern consigliato** per garantire compatibilità:

```typescript
const userPrompt = `${yourPrompt}\n\nReturn your response as valid JSON.`;
```

Questo aggiunge la parola "JSON" alla fine di qualsiasi prompt, garantendo che OpenAI accetti la richiesta.

**Note:**
- La parola può essere in qualsiasi parte del prompt (system o user)
- Può essere lowercase ("json"), uppercase ("JSON"), o mixed case ("Json")
- Varianti come "JSON format", "as JSON", "valid JSON" funzionano tutte
- Questo è lo **stesso requisito** della vecchia Chat Completions API con `response_format: { type: "json_object" }`

## Struttura Response - CRITICA!

La Responses API restituisce un array `output` che può contenere **più elementi**:

```json
{
  "id": "resp_...",
  "object": "response",
  "status": "completed",
  "output": [
    {
      "id": "rs_...",
      "type": "reasoning",  // ⚠️ PRIMO elemento = reasoning (NON contiene il testo!)
      "summary": []
    },
    {
      "id": "msg_...",
      "type": "message",    // ✅ SECONDO elemento = messaggio con il contenuto
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",  // Tipo del contenuto
          "text": "{ ... }"       // ✅ IL TESTO EFFETTIVO È QUI
        }
      ]
    }
  ]
}
```

### ⚠️ ERRORE COMUNE DA EVITARE

```typescript
// ❌ SBAGLIATO - output[0] è "reasoning", non "message"!
const text = data.output?.[0]?.content?.[0]?.text;

// ✅ CORRETTO - cerca l'elemento con type === "message"
let outputText = "";
if (data.output && Array.isArray(data.output)) {
  for (const item of data.output) {
    if (item.type === "message" && item.content && Array.isArray(item.content)) {
      for (const content of item.content) {
        if ((content.type === "output_text" || content.type === "text") && content.text) {
          outputText = content.text;
          break;
        }
      }
      if (outputText) break;
    }
  }
}
// Fallback per compatibilità
if (!outputText && data.output_text) {
  outputText = data.output_text;
}
```

## Helper Function Consigliata

```typescript
/**
 * Estrae il testo dalla risposta della Responses API di OpenAI.
 * Gestisce correttamente la struttura con reasoning + message.
 */
function extractResponseText(data: any, defaultValue: string = ""): string {
  if (data.output && Array.isArray(data.output)) {
    for (const item of data.output) {
      if (item.type === "message" && item.content && Array.isArray(item.content)) {
        for (const content of item.content) {
          if ((content.type === "output_text" || content.type === "text") && content.text) {
            return content.text;
          }
        }
      }
    }
  }
  // Fallback
  return data.output_text || defaultValue;
}

// Uso:
const responseData = await response.json();
const text = extractResponseText(responseData, "{}");
const parsed = JSON.parse(text);
```

## Streaming

Per lo streaming, la struttura degli eventi SSE è diversa:

```typescript
// Richiesta con streaming
body: JSON.stringify({
  model: "gpt-5-mini",
  input: [...],
  stream: true,
})

// Response: text/event-stream con eventi del tipo:
// data: {"type":"response.output_item.added",...}
// data: {"type":"response.content_part.added",...}
// data: {"type":"response.output_text.delta","delta":"Hello"}
// data: {"type":"response.output_text.done",...}
// data: [DONE]
```

## Parametri NON supportati da GPT-5-mini

- `temperature` - Usa sempre il default (1)
- `top_p` - Non specificare
- `frequency_penalty` / `presence_penalty` - Usare con cautela

## Edge Functions WarmAccess che usano Responses API

| Funzione | Modello | Scopo |
|----------|---------|-------|
| `check-message-bypass` | gpt-5-mini | Moderazione anti-bypass chat |
| `chat-suggestions` | gpt-5-mini | Suggerimenti risposte chat |
| `enrich-request` | gpt-5-mini | Arricchimento request (PII, spam, summary) |
| `enrich-offer` | gpt-5-mini | Arricchimento offer (PII, spam, summary) |
| `admin-enrich-all` | gpt-5-mini | Batch re-enrichment offers |
| `docs-support-chat` | gpt-5-mini | Chatbot supporto utenti |
| `admin-support-chat` | gpt-5 | Chatbot admin tecnico |
| `match-job-title` | gpt-5-mini | Matching job title multilingue |

## Funzioni che usano SOLO Embeddings (non Responses)

| Funzione | API | Scopo |
|----------|-----|-------|
| `instant-match` | `/v1/embeddings` | Ricerca semantica landing |
| `search-marketplace` | `/v1/embeddings` | Ricerca semantica dashboard |

## Nuova Funzione per Integrazione Apollo

| Funzione | Modello | Scopo |
|----------|---------|-------|
| `generate-icebreaker` | gpt-5-mini | Genera icebreaker personalizzato basato su dati Apollo (industry, keywords, technologies, employee count) |
| `apollo-data-enrichment` | gpt-5-mini | Arricchisce dati Apollo per creare insight personalizzati per email outreach |

**Esempio prompt per icebreaker Apollo:**
```typescript
const prompt = `Generate a personalized icebreaker based on company data:
Industry: ${industry}
Keywords: ${keywords}
Technologies: ${technologies}
Employee Count: ${employeeCount}
Revenue: ${revenue}

Return your response as valid JSON with fields: "icebreaker", "personalized_insight", "connection_point"`;
```

## Common Errors

### 400 Bad Request: Missing "json" in prompt

**Sintomo:**
```json
{
  "error": {
    "message": "Response input messages must contain the word 'json' in some form to use 'text.format' of type 'json_object'.",
    "type": "invalid_request_error"
  }
}
```

**Soluzione:** Aggiungi la parola "json" nel prompt (system o user). Vedi sezione "Requisito Critico" sopra.

### Read Timeout con prompt lunghi

**Sintomo:** Request timeout dopo 10-30s

**Causa:** Prompt molto lunghi (>5k tokens) + reasoning overhead

**Soluzione:**
- Aumenta timeout a 30s+ per prompt complessi
- Considera di ridurre `max_output_tokens` se non necessario
- GPT-5-mini genera reasoning traces che consumano tempo

## Riferimenti

- [OpenAI Responses API Docs](https://platform.openai.com/docs/api-reference/responses)
- [Migration Guide](https://platform.openai.com/docs/guides/migrate-to-responses)
- [GPT-5 Announcement](https://openai.com/blog/gpt-5)

---

**Ultimo aggiornamento**: Febbraio 2026
**Autore**: Sistema WarmAccess / ISCA Boris v2
**Changelog**:
- 2026-02-10: Aggiunta sezione CRITICA su requisito "json" nel prompt (causa 400 Bad Request)
