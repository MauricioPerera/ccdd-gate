<?php
function deep_nesting($items) {
    for ($a = 0; $a < count($items); $a++) {
        if ($a > 0) {
            while ($a > 0) {
                try {
                    if ($a > 0) {
                        return $a;
                    }
                } finally {
                }
            }
        }
    }
    return 0;
}
