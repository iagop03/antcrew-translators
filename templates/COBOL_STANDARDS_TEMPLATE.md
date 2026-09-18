# COBOL Coding Standards Template

Modify this file to match your company's actual standards, then pass it to the translator:

```bash
antcrew java-to-cobol OrderProcessor.java --standards COBOL_STANDARDS.md
```

---

## Variable Naming

### Working Storage Variables
Prefix: `WS-`

Examples:
- `WS-ORDER-AMOUNT`
- `WS-CUSTOMER-ID`
- `WS-STATUS-FLAG`

### Constants
Prefix: `WC-`

Examples:
- `WC-MAX-AMOUNT`
- `WC-BATCH-SIZE`
- `WC-ERROR-CODE-001`

### Linkage Section
Prefix: `LK-`

Examples:
- `LK-INPUT-RECORD`
- `LK-OUTPUT-FLAG`

### File Section
Prefix: `FD-`

Examples:
- `FD-ORDER-FILE`

---

## Naming Rules

- All UPPERCASE
- Words separated by dashes
- Maximum 29 characters (COBOL limit)
- No abbreviations except standard ones (ID, QTY, AMT, NO, DT)

---

## Paragraph Naming

### Pattern
`{ACTION}-{OBJECT}`

### Examples
- `CALCULATE-ORDER-TOTAL`
- `VALIDATE-CUSTOMER-ID`
- `PROCESS-TRANSACTION`
- `READ-NEXT-RECORD`
- `WRITE-OUTPUT-FILE`

### Rules
- Each paragraph = one logical function
- Max Nesting: 2
- Always end with a clear exit (STOP RUN or fall-through)
- Name clearly indicates the paragraph's purpose

---

## Structure Rules

### DATA DIVISION Organization
1. FILE SECTION (if files are used)
2. WORKING-STORAGE SECTION
   - Constants first (`WC-` prefixed, with VALUE clauses)
   - Then variables (`WS-` prefixed), grouped by domain
3. LINKAGE SECTION (if called as a subprogram)

### PROCEDURE DIVISION Organization
1. Main control paragraph first (calls subordinates via PERFORM)
2. Supporting paragraphs in order of execution
3. Error-handling paragraphs last

---

## Example Implementation

```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. ORDER-PROCESSOR.

DATA DIVISION.
WORKING-STORAGE SECTION.
01 WC-MAX-AMOUNT PIC 9(7)V99 VALUE 99999.99.
01 WC-MIN-AMOUNT PIC 9(7)V99 VALUE 0.00.
01 WS-ORDER-AMOUNT PIC 9(7)V99.
01 WS-CUSTOMER-ID PIC 9(8).
01 WS-STATUS-FLAG PIC X(2).

PROCEDURE DIVISION.
MAIN-PROCESS.
    PERFORM VALIDATE-ORDER.
    PERFORM CALCULATE-TOTAL.
    PERFORM UPDATE-STATUS.
    STOP RUN.

VALIDATE-ORDER.
    IF WS-ORDER-AMOUNT > WC-MAX-AMOUNT
        MOVE "ER" TO WS-STATUS-FLAG
    END-IF.

CALCULATE-TOTAL.
    COMPUTE WS-ORDER-AMOUNT = WS-ORDER-AMOUNT * 1.21.

UPDATE-STATUS.
    IF WS-STATUS-FLAG = SPACES
        MOVE "OK" TO WS-STATUS-FLAG
    END-IF.
```
