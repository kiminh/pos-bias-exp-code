#!/bin/bash

data_path=$1
mode=$2
pos_bias=$3
part=$4

if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
	echo "Plz input data_path & mode & pos_bias!!!!!"
	exit 0 
fi

if [ -z "$4" ]; then
	part='all'
fi

exp_parts="der.0.01,der.0.1,der.comb.0.01.imp,der.comb.0.1.imp,der.comb.0.01,der.comb.0.1,derive.det,derive.random,all"
pass="No"
Backup_of_internal_field_separator=$IFS
IFS=,
for item in ${exp_parts};
do
	if [ ${item} == ${part} ]; then
		pass="Yes"
	fi
done
IFS=$Backup_of_internal_field_separator

if [ "${pass}" == "No" ]; then
	echo "exp part should be one of ${exp_parts}!"
	exit 0
fi
echo "runing exps on the part-${part} of ${data_path} at mode-${mode} with pos_bias-${pos_bias}"

root=`pwd`
run_exp(){
	cdir=$1
	rdir=$2
	mode=$3
	cmd="cd ${cdir}"
	#cmd="${cmd}; echo ${cdir}"
	cmd="${cmd}; ./grid.sh" 
	cmd="${cmd}; ./do-test.sh ${mode}"
	#cmd="${cmd}; ./auto-pred.sh"
	cmd="${cmd}; echo 'va_logloss va_auc' > ${mode}.record"
	cmd="${cmd}; python select_params.py logs ${mode} | rev | cut -d' ' -f1-2 | rev >> ${mode}.record"
	#cmd="${cmd}; python cal_auc.py test-score.${mode}/  rnd_gt.ffm ${pos_bias} >> ${mode}.record"
	cmd="${cmd}; tail -n2 test-score.${mode}/*.log | rev | cut -d' ' -f1-2 | rev >> ${mode}.record"
	#cmd="${cmd}; cat test-score/[0-4].log | awk '{sum+=\$1} END {print \"Average = \", sum/NR}'"
	cmd="${cmd}; cd ${rdir}"
	echo ${cmd}
}

run_exp_imp(){
	cdir=$1
	rdir=$2
	mode=$3
	cmd="cd ${cdir}"
	cmd="${cmd}; ./grid.sh" 
	#cmd="${cmd}; ./select_params.sh logs ${mode}"
	cmd="${cmd}; ./do-test.sh ${mode}"
	cmd="${cmd}; echo 'va_logloss va_auc' > ${mode}.record"
	cmd="${cmd}; cat ${mode}.stats | rev | cut -d' ' -f1-2 | rev >> ${mode}.record"
	#cmd="${cmd}; echo 'te_logloss te_auc' > ${mode}.record"
	cmd="${cmd}; tail -n1 test-score.${mode}/*.log | rev | cut -d' ' -f1-2 | rev >> ${mode}.record"
	cmd="${cmd}; cd ${rdir}"
	echo ${cmd}
}

set -e
exp_dir=`basename ${data_path}`
for i in 'det' 'random'
do
	if [ "${part}" != 'all' ]; then
		if [ "${part}" != "derive.$i" ]; then
			continue
		fi
	fi
	cdir=${exp_dir}/derive.${i}
	mkdir -p ${cdir}
	ln -sf ${root}/scripts/init.sh ${cdir}
	ln -sf ${root}/scripts/grid.sh ${cdir}
	ln -sf ${root}/scripts/do-test.sh ${cdir}
	ln -sf ${root}/scripts/select_params.py ${cdir}
	ln -sf ${root}/hybrid-ocffm/train ${cdir}/hytrain
	ln -sf ${root}/${data_path}/derive/*gt*ffm ${cdir}
	ln -sf ${root}/${data_path}/derive/item.ffm ${cdir}
	for j in 'trva' 'tr' 'va'
	do
		ln -sf ${root}/${data_path}/derive/${i}_${j}.ffm ${cdir}/${j}.ffm
	done
	run_exp ${cdir} ${root} ${mode} | xargs -0 -d '\n' -P 1 -I {} sh -c {} 
done

for i in '.comb.' '.'
do 
	for k in 0.01 0.1
	do 
		if [ "${part}" != 'all' ]; then
			if [ "${part}" != "der${i}${k}" ]; then
				continue
			fi
		fi
		cdir=${exp_dir}/der${i}${k}
		mkdir -p ${cdir}
		ln -sf ${root}/scripts/init.sh ${cdir}
		ln -sf ${root}/scripts/grid.sh ${cdir}
		ln -sf ${root}/scripts/do-test.sh ${cdir}
		ln -sf ${root}/scripts/select_params.py ${cdir}
		ln -sf ${root}/hybrid-ocffm/train ${cdir}/hytrain
		ln -sf ${root}/${data_path}/der${i}${k}/*gt*ffm ${cdir}
		ln -sf ${root}/${data_path}/der${i}${k}/item.ffm ${cdir}
		for j in 'trva' 'tr' 'va'
		do
			ln -sf ${root}/${data_path}/der${i}${k}/select_${j}.ffm ${cdir}/${j}.ffm
		done
		run_exp ${cdir} ${root} ${mode} | xargs -0 -d '\n' -P 1 -I {} sh -c {} 
	done
done

for i in '.comb.' 
do 
	for k in 0.01 0.1
	do 
		if [ "${part}" != 'all' ]; then
			if [ "${part}" != "der${i}${k}.imp" ]; then
				continue
			fi
		fi
		cdir=${exp_dir}/der${i}${k}.imp
		mkdir -p ${cdir}
		ln -sf ${root}/scripts/init.sh ${cdir}
		ln -sf ${root}/scripts/grid-imp.sh ${cdir}/grid.sh
		ln -sf ${root}/scripts/do-test-imp.sh ${cdir}/do-test.sh
		ln -sf ${root}/scripts/select_params.sh ${cdir}
		ln -sf ${root}/tfboys-complex/train ${cdir}/train
		ln -sf ${root}/${data_path}/der${i}${k}.imp/*gt*ffm ${cdir}
		ln -sf ${root}/${data_path}/der${i}${k}.imp/item.ffm ${cdir}
		for j in 'trva' 'tr'
		do
			cat ${root}/${data_path}/der${i}${k}.imp/select_*_${j}.ffm > ${cdir}/${j}.ffm
		done
		for j in 'trva' 'tr'
		do
			ln -sf ${root}/${data_path}/der${i}${k}.imp/select_st_${j}.ffm ${cdir}/imp_${j}.ffm
		done
		ln -sf ${root}/${data_path}/der${i}${k}.imp/select_va.ffm ${cdir}/va.ffm
		run_exp_imp ${cdir} ${root} ${mode} | xargs -0 -d '\n' -P 1 -I {} sh -c {} 
	done
done
exit 0

## Check command
#echo "Check command list (the command may not be runned!!)"
#task
#wait


# Run
#echo "Run"
#task | xargs -0 -d '\n' -P 4 -I {} sh -c {} 
