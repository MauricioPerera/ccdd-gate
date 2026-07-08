// when con 3 ramas + else: cada when_entry suma +1 INCLUIDO else (la gramatica no
// distingue la rama else por tipo de nodo; modelo TS/Java, espejo de switch_label).
fun switch_case(x: Int): Int {
    when (x) {
        0 -> return 0
        1 -> return 1
        2 -> return 2
        else -> return 3
    }
    return -1
}
