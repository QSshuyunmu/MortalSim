param(
    [int]$conc,
    [int]$threads,
    [int]$seeds,
    [string]$rayon,
    [string]$tag
)
$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
$env:RAYON_NUM_THREADS = $rayon
$env:OMP_NUM_THREADS = $rayon
$env:MKL_NUM_THREADS = $rayon
& $py -X utf8 C:\arena\bench_conc.py --conc $conc --threads $threads --seeds $seeds --tag $tag
