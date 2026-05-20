# FAQs

## My model doesn't run, how do I find the issue?

First places to look are the command line (usually Anaconda prompt) and the log file as it displays the error it found in the model, sometimes it is not as clear as 'X' is wrong but it might say demand contraint failed to be met, which points there is an issue in the demand table.

## My model ran but how do I know if it is working as intended?

Best practice is to make mass/energy balances of the technologies you are curious about, we know the efficiency and the amount of each commodity that should be going in so we should be able to contruct a balance to compare the results to.

## My model ran but the flows in and out of technologies doesn't make sense?

Look at the commodity maps and log file to determine if there are any orphans (either supply side or demand-side). If orphans are present, the techinputsplit can often be disregarded if they use the orphaned commodity allowing for weird results such as using only electricity to create steel without the need for iron...

## The command line said the model is infeasible but I don't know why?

Infeasibilities usually come from constraints, if your model is infeasible after 0 second solve time, look at the constraints such as limitactivity, limitcapacity etc.

## I completed my project and want my new section to be apart of the model, how do I go about that?

Please contact the adminstration team and they will review the work done. If the work done is modular and able to be attached to the model as it is, then it is more likely to be approved. If approved, we will include in the next annual release.