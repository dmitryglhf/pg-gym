import { define } from "@/utils.ts";
import Platform from "@/islands/Platform.tsx";
export default define.page(({ params }) => (
  <Platform page="job" id={params.id} />
));
