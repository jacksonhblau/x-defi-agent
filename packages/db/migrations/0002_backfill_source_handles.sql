-- Backfill source_handles on existing stories whose source_handles is empty.
-- Derived from the signals each story was promoted from.

update stories s
set source_handles = array(
    select distinct case sig.source
        when 'defillama'         then '@DefiLlama'
        when 'rwa_xyz'           then '@rwa_xyz'
        when 'telegram_newswire' then '@RWAxyzNewswire'
        when 'vaultsfyi'         then '@vaultsfyi'
        when 'bubblemaps'        then '@bubblemaps'
        when 'etherscan'         then '@etherscan'
        else null
    end
    from signals sig
    where sig.id = any(s.signals_ids)
      and case sig.source
          when 'defillama'         then true
          when 'rwa_xyz'           then true
          when 'telegram_newswire' then true
          when 'vaultsfyi'         then true
          when 'bubblemaps'        then true
          when 'etherscan'         then true
          else false
      end
)
where (s.source_handles is null or s.source_handles = '{}');
