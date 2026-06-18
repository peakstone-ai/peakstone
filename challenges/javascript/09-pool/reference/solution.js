export async function pool(thunks, concurrency) {
  const results = new Array(thunks.length);
  let next = 0;

  async function worker() {
    while (next < thunks.length) {
      const i = next++;
      results[i] = await thunks[i]();
    }
  }

  const workers = [];
  const n = Math.min(concurrency, thunks.length);
  for (let w = 0; w < n; w++) {
    workers.push(worker());
  }
  await Promise.all(workers);
  return results;
}
