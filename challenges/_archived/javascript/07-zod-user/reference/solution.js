import { z } from "zod";

const userSchema = z.object({
  name: z.string().min(1),
  age: z.number().int().min(0),
  email: z.email(),
});

export function validateUser(obj) {
  const result = userSchema.safeParse(obj);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return {
    success: false,
    errors: result.error.issues.map((issue) => issue.message),
  };
}
