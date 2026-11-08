import { PILOT_QUESTION_IDS, type PilotExpectations } from "../../src/grading/catalogue/oakridge-questions";

// The pinned grading fixture also opens a scratch Postgres database. These tests only read its
// pinned expectations, which are the same for every pilot question, so only those ship.
export const pinnedExpectation = { definition_id: "definition-1", artifact_schema_version: "1" };
export const pilotExpectations = Object.fromEntries(
  PILOT_QUESTION_IDS.map((question_id) => [question_id, pinnedExpectation])) as PilotExpectations;
