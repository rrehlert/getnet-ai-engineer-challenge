# Getnet Multi-Agent Support

A support assistant for Getnet merchants. It answers product questions from Getnet's public content and account questions from the merchant's own data.

## Conversation

**Message**:
One piece of text a Merchant sends, with their login token. Handled independently; there is no conversation history.
_Avoid_: Query, prompt, request

**Merchant**:
A Getnet customer business, identified by a user id (e.g. `cliente1988`), that owns Terminals and receives Settlements. The Merchant is always the one named by the verified login token (its `sub`), never by the request body. Text inside a Message never changes who the Merchant is.
_Avoid_: User, client, customer, lojista

**Operator**:
A Getnet staff member who logs in with role `operator` (not a Merchant). Operators cannot chat as a Merchant; their actions come with the human takeover.
_Avoid_: Agent (taken by the AI Agents), admin, attendant

**Intent**:
The Router Agent's classification of a Message: `knowledge`, `support`, or `unsupported`.
_Avoid_: Category, route, topic

## Agents

**Router Agent**:
The entry point. It assigns each Message an Intent and either hands it to a specialist or refuses it itself when it is unsupported.
_Avoid_: Orchestrator, classifier, supervisor

**Knowledge Agent**:
The specialist for general questions: Getnet products and services (from the Corpus) and general facts such as weather or exchange rates (from web search).
_Avoid_: RAG agent, FAQ agent, search agent

**Customer Support Agent**:
The specialist for questions about the Merchant's own account, such as Settlements, Terminals and recent transactions.
_Avoid_: Support bot, account agent, helpdesk

## Knowledge

**Corpus**:
The set of Getnet web pages, saved as text, that the Knowledge Agent can search.
_Avoid_: Knowledge base, dataset, documents

**Chunk**:
A short passage of a Corpus page, labelled with that page's title. It is the unit that retrieval returns.
_Avoid_: Passage, snippet, document

**Source**:
A page (URL and title) that a retrieval or web search tool actually returned and that supports an answer. Sources are never taken from model-written text.
_Avoid_: Citation, reference, link

**Evidence**:
The tool output an Agent actually saw while answering a Message: the Chunks a search returned or the account data a tool returned. A Source names where something came from; Evidence is what it said. Judges rate replies against Evidence.
_Avoid_: Context, grounding, retrieved docs

## Merchant account

**Settlement**:
A scheduled deposit of a Merchant's sales proceeds into their account, with an expected date, amount and status.
_Avoid_: Payout, deposit, repasse, liquidação

**Terminal**:
A Getnet card machine (POS) owned by a Merchant.
_Avoid_: Machine, POS, maquininha, device

## Quality

**Judge Type**:
The aspect an LLM judge rates after a reply is sent. `route` asks whether the Intent was right. `answer` asks whether every claim in the reply is supported by the Evidence and the reply answers the Message. `coverage` lists the Intents the Message needed and whether the reply covered every part (it detects a Mixed question).
_Avoid_: Judge kind, eval category

**Judge Score**:
A 0–1 rating of one Message under one Judge Type. A score below 0.7 is flagged.
_Avoid_: Eval score, rating, confidence

**Mixed question**:
A Message that needs more than one specialist to answer fully, e.g. a Terminal that is offline plus how to set up Wi-Fi (Customer Support and Knowledge). The Router picks one Intent per Message.
_Avoid_: Multi-intent message, compound question
