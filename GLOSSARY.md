# Getnet Multi-Agent Support

A support assistant for Getnet merchants. It answers product questions from Getnet's public content and account questions from the merchant's own data.

## Conversation

**Message**:
One piece of text a Merchant (with their login token, optionally continuing a Conversation) or an Anonymous visitor (always on its own, nothing stored) sends.
_Avoid_: Query, prompt, request

**Conversation**:
An ordered series of Turns owned by one Merchant, identified by a random id. A Merchant's first Message starts one; follow-ups name it. Another Merchant's Conversation is indistinguishable from one that doesn't exist. Operators see only Conversations that had a Handoff or carry a Review flag.
_Avoid_: Session, thread, chat

**Turn**:
One entry in a Conversation: a Message (`user`), a reply from an Agent (`assistant`), or a reply from an Operator (`operator`). Stores the text, Intent and Sources, never Evidence. The last 10 Turns before a Message are its history: every Agent sees them as context, but account facts always come from fresh tool calls.
_Avoid_: Message (that is only the Merchant's side), exchange, entry

**Merchant**:
A Getnet customer business, identified by a user id (e.g. `cliente1988`), that owns Terminals and receives Settlements. The Merchant is always the one named by the verified login token (its `sub`), never by the request body. Text inside a Message never changes who the Merchant is.
_Avoid_: User, client, customer, lojista

**Anonymous visitor**:
Someone who sends a Message without a login token. There is no Merchant, so only the Knowledge Agent can answer: account questions and requests for a person get a fixed "log in" reply, the Customer Support Agent never runs, and there is no Escalation. Nothing is remembered between their Messages. A bad token never makes someone an Anonymous visitor; it is rejected.
_Avoid_: Guest, anonymous user, public user

**Operator**:
A Getnet staff member who logs in with role `operator` (not a Merchant). Operators cannot chat as a Merchant; they claim waiting Conversations and reply to the Merchant during a Handoff.
_Avoid_: Agent (taken by the AI Agents), admin, attendant

**Intent**:
The Router Agent's classification of a Message: `knowledge`, `support`, `human` (the Merchant asks for a person), or `unsupported`.
_Avoid_: Category, route, topic

**Mode**:
Who answers a Conversation right now: `bot` (the Agents), `waiting_human` (escalated, no Operator yet), `human` (an Operator has claimed it), or `closed` (finished; the Merchant starts a new Conversation). Outside `bot`, the Agents don't answer: Messages wait for the Operator.
_Avoid_: State, status, takeover flag

**Escalation**:
The act that hands a Conversation from the Agents to a human: the Merchant asks for a person, or a specialist decides it cannot resolve the case. It starts a Handoff and moves the Conversation to `waiting_human`.
_Avoid_: Transfer, takeover

**Handoff**:
One episode of human help in a Conversation, from Escalation until the Operator hands it back to the Agents or closes it. It holds the Handoff Brief, the claiming Operator and the outcome. A Conversation has any number of Handoffs over time, at most one open.
_Avoid_: Takeover, ticket, case

**Handoff Brief**:
The Escalator Agent's summary of a Handoff for the Operator: why it escalated, what the Merchant wants, what the Agents already tried, category, priority and a suggested reply. The suggested reply is only ever sent by an Operator's choice. Account facts shown to the Operator come from the system, never from the brief.
_Avoid_: Summary, ticket description, handover note

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

**Escalator Agent**:
The fourth Agent. On an Escalation it writes the Handoff Brief and tells the Merchant, in their language, that they are being transferred. It summarises; it does not investigate or call tools.
_Avoid_: Handoff agent, human agent, escalation bot

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

**Review flag**:
A mark on a Conversation whose Agent reply got a low `answer` Judge Score. Operators review flagged Conversations after the fact and clear the flag; it never changes the Mode or blocks the Merchant.
_Avoid_: needs review, alert, escalation
