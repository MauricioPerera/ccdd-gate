/* Anidamiento profundo (5 niveles: for>if>while>bloque etiquetado>if). El bloque
   etiquetado (labeled_statement, idioma del goto de limpieza) anida SIN ser
   decision: es el analogo local del `with` de Python (C no tiene try/with/lock). */
int deep_nesting(int n) {
    for (int a = 0; a < n; a++) {
        if (a > 0) {
            while (a > 0) {
                cleanup: {
                    if (a > 0) {
                        return a;
                    }
                }
            }
        }
    }
    return 0;
}
