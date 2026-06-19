const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function retry(fn, { retries = 3, baseDelayMs = 10 } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt < retries) {
        await sleep(baseDelayMs * 2 ** attempt);
      }
    }
  }
  throw lastError;
}
