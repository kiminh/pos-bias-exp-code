# Train file path
train='./hytrain'

# Fixed parameter
t=50
wn=1
r=-1
c=5

# Data set
tr='tr.ffm'
va='va.ffm'
item='item.ffm'

# Log path
log_path="logs"
mkdir -p $log_path


task(){
# Set up fixed parameter and train command
train_cmd="${train} -t ${t} -wn ${wn} -r ${r} -c ${c} --ns"

# Print out all parameter pair
for l in 16 32 64
do
    for w in 0 
    do
        for k in 16 32 64
        do
            cmd=${train_cmd}
            cmd="${cmd} -l ${l}"
            cmd="${cmd} -w ${w}"
            cmd="${cmd} -k ${k}"
            echo "${cmd} -p ${va} ${item} ${tr} > ${log_path}/$l.$w.$k.log"
        done
    done
done
}


# Check command
echo "Check command list (the command may not be runned!!)"
task
wait


# Run
echo "Run"
task | xargs -0 -d '\n' -P 3 -I {} sh -c {} &
