                    INPUT CSV / XLSX
                          │
                          ▼
              ┌──────────────────────┐
              │     Read Input       │
              │ Service Name         │
              │ Service Website      │
              │ Postcode             │
              │ Town                 │
              └──────────┬───────────┘
                         │
                         ▼
                Website already given?
                    /            \
                  YES             NO
                   │               │
                   │               ▼
                   │       Service Name + Postcode
                   │               │
                   │               ▼
                   │        Serper / Google
                   │               │
                   │               ▼
                   │      Evaluate ALL results
                   │               │
                   │               ▼
                   │       Find relevant website
                   │
                   └───────┬───────┘
                           ▼
                  SELECTED WEBSITE
                           │
                           ▼
              ┌────────────────────────┐
              │ Identify website type  │
              └────────────┬───────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
      DIRECT SERVICE WEBSITE      ORG / SERVICE PAGE
             │                           │
             │                           ▼
             │                 Check selected page FIRST
             │                           │
             │                    Service-specific
             │                       email?
             │                     /          \
             │                   YES           NO
             │                    │             │
             │                    ▼             │
             │             Use service email    │
             │                    │             │
             │                    │             ▼
             │                    │      Existing fallback
             │                    │      crawling strategy
             │                    │             │
             └──────────────┬─────┴─────────────┘
                            ▼
                     EMAIL EXTRACTION
                            │
                            ▼
                     EMAIL VALIDATION
                            │
                            ▼
                     IGNORE FILTERING
                            │
                            ▼
                    CATEGORY PRIORITY
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
             HR        Recruitment       Careers
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                         Manager
                            ▼
                           Info
                            ▼
                         General
                            │
                            ▼
                       DEDUPLICATION
                            │
                            ▼
                       RESULT RECORD
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
             SUCCESS                  FAILED
                │                       │
                └───────────┬───────────┘
                            ▼
                     CHECKPOINT SAVE
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         Enriched        Success        Failed