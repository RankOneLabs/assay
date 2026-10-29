import { PROVISION_REPOSITORY_REFS_STAGE_TYPE } from "../domain/repository-refs";
import type { StageTypeCompiler, StageTypeCompilerRegistry } from "./compile-workflow";

export const registerBuiltInCompilers = (
  delegated: StageTypeCompiler,
  repository: StageTypeCompiler,
): StageTypeCompilerRegistry => ({
  delegated_session: delegated,
  [PROVISION_REPOSITORY_REFS_STAGE_TYPE]: repository,
});
