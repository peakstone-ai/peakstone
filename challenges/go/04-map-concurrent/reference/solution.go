package challenge

import "sync"

// MapConcurrent applies fn to every element of inputs using at most `workers`
// concurrent goroutines, returning results in the same order as inputs.
func MapConcurrent(inputs []int, workers int, fn func(int) int) []int {
	results := make([]int, len(inputs))
	if len(inputs) == 0 {
		return results
	}
	if workers < 1 {
		workers = 1
	}
	if workers > len(inputs) {
		workers = len(inputs)
	}

	jobs := make(chan int) // sends indices into inputs/results
	var wg sync.WaitGroup
	wg.Add(workers)
	for w := 0; w < workers; w++ {
		go func() {
			defer wg.Done()
			for i := range jobs {
				results[i] = fn(inputs[i]) // distinct index per job => no data race
			}
		}()
	}
	for i := range inputs {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	return results
}
