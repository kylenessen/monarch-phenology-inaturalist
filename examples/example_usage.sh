#!/bin/bash
# Example usage of the GBIF Taxa Analysis Tool

# Example 1: Verify that Lepidoptera makes up ~10% of total diversity
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera --output lepidoptera_analysis

# Example 2: Compare major insect orders
python gbif_taxa_analysis.py --rank ORDER \
    --compare Lepidoptera,Coleoptera,Diptera,Hymenoptera,Hemiptera,Orthoptera \
    --output insect_orders_comparison

# Example 3: Compare different taxonomic classes
python gbif_taxa_analysis.py --rank CLASS \
    --compare Insecta,Arachnida,Mammalia,Aves,Reptilia,Amphibia,Actinopterygii \
    --output vertebrates_vs_invertebrates

# Example 4: Analyze top 10 orders (note: limited by API, may not be the true top 10)
python gbif_taxa_analysis.py --rank ORDER --top 10 --output top_10_orders

# Example 5: Compare phyla
python gbif_taxa_analysis.py --rank PHYLUM \
    --compare Arthropoda,Mollusca,Chordata,Annelida,Cnidaria,Echinodermata \
    --output major_phyla

# Example 6: Use GBIF's total count instead of Catalogue of Life
# (Warning: this may give inflated percentages)
python gbif_taxa_analysis.py --rank ORDER --compare Lepidoptera \
    --use-gbif-total \
    --output lepidoptera_gbif_total

# Example 7: Compare plant orders
python gbif_taxa_analysis.py --rank ORDER \
    --compare Asterales,Fabales,Rosales,Poales,Lamiales \
    --output plant_orders
