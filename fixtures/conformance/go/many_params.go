package main

// Parámetros agrupados que comparten tipo (forma idiomática de Go): un solo
// parameter_declaration con seis identifier hijos. El backend debe contar por
// NOMBRE declarado (6), no por declaración (1) — ver _go_param_count.
func many_params(a, b, c, d, e, f int) int {
	return a + b + c + d + e + f
}